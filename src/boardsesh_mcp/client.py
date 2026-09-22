"""HTTP client for the Boardsesh API. Knows nothing about MCP.

Two transports, both read-only from this client's point of view:

* GraphQL over HTTP POST for everything except the heatmap. Only the pinned documents in
  ``queries`` are ever sent.
* One REST route for the hold heatmap, which returns JSON hold counts.

Boardsesh degrades an invalid or expired token to *anonymous* rather than returning 401, so an
auth failure surfaces as a resolver error. ``_is_auth_error`` detects that and retries once with
a fresh token.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx2

from boardsesh_mcp import queries as q
from boardsesh_mcp.auth import AuthError, TokenManager
from boardsesh_mcp.config import Settings, redact
from boardsesh_mcp.endpoints import GRAPHQL_URL, USER_AGENT, heatmap_url
from boardsesh_mcp.grades import GradeTable
from boardsesh_mcp.models import Ascent, BoardTickCount, ClimbSuggestion, Grade, HoldStat

AUTH_ERROR_MARKER = "authentication required"


class BoardseshAPIError(RuntimeError):
    """The Boardsesh API returned an error. Message is safe to show to the agent."""


@dataclass(frozen=True)
class BoardConfig:
    """A board configuration: the five coordinates every catalogue query needs."""

    board: str
    layout_id: int
    size_id: int
    set_ids: str
    angle: int
    name: str | None = None
    layout_name: str | None = None
    size_name: str | None = None
    uuid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "board": self.board,
            "name": self.name,
            "layout": self.layout_name,
            "size": self.size_name,
            "angle": self.angle,
            "layout_id": self.layout_id,
            "size_id": self.size_id,
            "set_ids": self.set_ids,
        }

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> BoardConfig | None:
        try:
            return cls(
                board=str(raw["boardType"]),
                layout_id=int(raw["layoutId"]),
                size_id=int(raw["sizeId"]),
                set_ids=str(raw["setIds"]),
                angle=int(raw["angle"]),
                name=raw.get("name"),
                layout_name=raw.get("layoutName"),
                size_name=raw.get("sizeName"),
                uuid=raw.get("uuid"),
            )
        except (KeyError, TypeError, ValueError):
            return None


class BoardseshClient:
    """Read-only access to one Boardsesh user's data.

    ``http`` is injectable so tests can pass an ``httpx2.AsyncClient`` with a ``MockTransport``.
    """

    def __init__(
        self,
        settings: Settings,
        http: httpx2.AsyncClient | None = None,
        *,
        token_manager: TokenManager | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_rate_limit_retries: int = 2,
        max_retry_after_seconds: float = 30.0,
    ) -> None:
        self._settings = settings
        self._sleep = sleep
        self._max_rate_limit_retries = max_rate_limit_retries
        self._max_retry_after_seconds = max_retry_after_seconds
        self._owns_http = http is None
        self._http = http or httpx2.AsyncClient(
            timeout=settings.timeout_seconds,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        self._tokens = token_manager or TokenManager(settings, self._http)
        self._user_id: str | None = settings.user if settings.user_is_id else None
        self._display_name: str | None = None
        self._grades: dict[str, GradeTable] = {}

    def __repr__(self) -> str:
        return f"BoardseshClient(user={self._settings.user!r})"

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    @property
    def authenticated(self) -> bool:
        return self._settings.has_credentials

    # -- identity ---------------------------------------------------------------------------

    async def resolve_user(self) -> tuple[str, str | None]:
        """Return (user_id, display_name) for the configured user.

        ``BOARDSESH_USER`` may be a user id (used as-is) or a display name, which is looked up
        with the public user search. An exact case-insensitive match wins; otherwise the most
        recently active match is used.
        """
        if self._user_id is not None:
            if self._display_name is None:
                data = await self._graphql(q.PUBLIC_PROFILE, {"userId": self._user_id})
                profile = (data or {}).get("publicProfile") or {}
                self._display_name = profile.get("displayName")
            return self._user_id, self._display_name

        wanted = self._settings.user
        data = await self._graphql(q.SEARCH_USERS, {"query": wanted, "limit": 25})
        results = ((data or {}).get("searchUsers") or {}).get("results") or []
        if not results:
            raise BoardseshAPIError(
                f"No Boardsesh user found matching {wanted!r}. Check BOARDSESH_USER: it should "
                "be your Boardsesh display name or your user id."
            )
        exact = [
            r
            for r in results
            if str((r.get("user") or {}).get("displayName") or "").lower() == wanted.lower()
        ]
        pool = exact or results
        pool.sort(key=lambda r: -(r.get("recentAscentCount") or 0))
        user = pool[0].get("user") or {}
        user_id = user.get("id")
        if not user_id:
            raise BoardseshAPIError(f"Boardsesh returned no user id for {wanted!r}.")
        if not exact and len(results) > 1:
            names = ", ".join(
                sorted({str((r.get("user") or {}).get("displayName") or "?") for r in results[:5]})
            )
            raise BoardseshAPIError(
                f"{wanted!r} did not match a Boardsesh display name exactly. Candidates: "
                f"{names}. Set BOARDSESH_USER to the exact display name or to your user id."
            )
        self._user_id = str(user_id)
        self._display_name = user.get("displayName")
        return self._user_id, self._display_name

    async def get_viewer_id(self) -> str | None:
        """The authenticated user's own id, or None when running without credentials."""
        if not self.authenticated:
            return None
        data = await self._graphql(q.VIEWER_PROFILE, {}, authenticated=True)
        return ((data or {}).get("profile") or {}).get("id")

    # -- logbook ----------------------------------------------------------------------------

    async def get_tick_counts(self) -> list[BoardTickCount]:
        """Ticks per board type. Cheapest way to learn which boards the user actually uses."""
        user_id, _ = await self.resolve_user()
        data = await self._graphql(q.TICK_COUNTS_BY_BOARD, {"userId": user_id})
        rows = (data or {}).get("userTickCountsByBoard") or []
        counts = [c for c in (BoardTickCount.from_api(r) for r in rows if isinstance(r, dict)) if c]
        counts.sort(key=lambda c: -c.count)
        return counts

    async def get_profile_stats(self) -> dict[str, Any]:
        """Distinct climb counts per grade per layout, plus the user's percentile."""
        user_id, _ = await self.resolve_user()
        data = await self._graphql(q.PROFILE_STATS, {"userId": user_id})
        return data or {}

    async def get_ascents(self, **feed_input: Any) -> tuple[list[Ascent], int, bool]:
        """One page of the logbook feed. Returns (ascents, total_count, has_more).

        This is the only genuinely multi-board read: pass ``boardTypes=[...]``.
        """
        user_id, _ = await self.resolve_user()
        payload = {k: v for k, v in feed_input.items() if v is not None}
        data = await self._graphql(q.ASCENTS_FEED, {"userId": user_id, "input": payload})
        feed = (data or {}).get("userAscentsFeed") or {}
        items = feed.get("items") or []
        ascents = [Ascent.from_feed_item(i) for i in items if isinstance(i, dict)]
        return ascents, int(feed.get("totalCount") or 0), bool(feed.get("hasMore"))

    async def get_all_ascents(self, *, page_size: int = 50, max_pages: int = 40, **feed_input: Any):
        """Page through the whole logbook (feed pages are capped at 50 server-side)."""
        out: list[Ascent] = []
        total = 0
        for page in range(max_pages):
            batch, total, has_more = await self.get_ascents(
                limit=page_size, offset=page * page_size, **feed_input
            )
            out.extend(batch)
            if not has_more or not batch:
                break
        return out, total

    async def get_smart_playlist(self, playlist_type: str, **extra: Any) -> dict[str, Any]:
        """A computed list: PROJECTS, FIVE_STARS, MOST_REPEATED, RECOMMENDED_AT_LEVEL, ..."""
        user_id, _ = await self.resolve_user()
        payload = {"type": playlist_type, "userId": user_id}
        payload.update({k: v for k, v in extra.items() if v is not None})
        data = await self._graphql(q.SMART_PLAYLIST, {"input": payload})
        result = (data or {}).get("smartPlaylist") or {}
        climbs = [
            c
            for c in (
                ClimbSuggestion.from_api(r)
                for r in (result.get("climbs") or [])
                if isinstance(r, dict)
            )
            if c
        ]
        return {
            "climbs": climbs,
            "total_count": int(result.get("totalCount") or 0),
            "has_more": bool(result.get("hasMore")),
        }

    # -- catalogue --------------------------------------------------------------------------

    async def search_climbs(self, **search_input: Any) -> dict[str, Any]:
        payload = {k: v for k, v in search_input.items() if v is not None}
        data = await self._graphql(
            q.SEARCH_CLIMBS, {"input": payload}, authenticated=self.authenticated
        )
        result = (data or {}).get("searchClimbs") or {}
        climbs = [
            c
            for c in (
                ClimbSuggestion.from_api(r, board=payload.get("boardName"))
                for r in (result.get("climbs") or [])
                if isinstance(r, dict)
            )
            if c
        ]
        return {
            "climbs": climbs,
            "total_count": int(result.get("totalCount") or 0),
            "has_more": bool(result.get("hasMore")),
        }

    async def similar_climbs(self, **similar_input: Any) -> list[ClimbSuggestion]:
        payload = {k: v for k, v in similar_input.items() if v is not None}
        data = await self._graphql(q.SIMILAR_CLIMBS, {"input": payload})
        rows = (data or {}).get("similarClimbs") or []
        return [
            c
            for c in (
                ClimbSuggestion.from_api(r, board=payload.get("boardType"))
                for r in rows
                if isinstance(r, dict)
            )
            if c
        ]

    async def get_grades(self, board: str) -> GradeTable:
        """Board-native grade table. Cached per board for the process lifetime."""
        if board in self._grades:
            return self._grades[board]
        try:
            data = await self._graphql(q.GRADES, {"boardName": board})
            rows = (data or {}).get("grades") or []
            grades = [g for g in (Grade.from_api(r) for r in rows if isinstance(r, dict)) if g]
            table = (
                GradeTable.from_grades(grades, source="api") if grades else GradeTable.fallback()
            )
        except BoardseshAPIError:
            table = GradeTable.fallback()
        self._grades[board] = table
        return table

    # -- boards (viewer-only) ---------------------------------------------------------------

    async def get_my_boards(self) -> tuple[BoardConfig | None, list[BoardConfig]]:
        """The viewer's default board and saved boards. Requires credentials."""
        data = await self._graphql(q.MY_BOARDS, {}, authenticated=True)
        default_raw = (data or {}).get("defaultBoard")
        default = BoardConfig.from_api(default_raw) if isinstance(default_raw, dict) else None
        rows = ((data or {}).get("myBoards") or {}).get("boards") or []
        boards = [b for b in (BoardConfig.from_api(r) for r in rows if isinstance(r, dict)) if b]
        return default, boards

    # -- heatmap (REST) ---------------------------------------------------------------------

    async def get_hold_heatmap(
        self, config: BoardConfig, *, params: dict[str, Any] | None = None
    ) -> list[HoldStat]:
        """Per-hold usage counts for a board configuration.

        Community columns always come back. ``user_ascents`` / ``user_attempts`` require a
        session cookie, which this client does not have, so they are normally absent; the
        analytics layer reconstructs the user's own hold usage from their logbook instead.
        """
        url = heatmap_url(
            config.board, config.layout_id, config.size_id, config.set_ids, config.angle
        )
        payload = await self._get_json(url, params=params or {})
        rows = payload.get("holdStats") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise BoardseshAPIError(
                f"Boardsesh returned an unexpected heatmap response for {config.board}."
            )
        return [h for h in (HoldStat.from_api(r) for r in rows if isinstance(r, dict)) if h]

    # -- internals --------------------------------------------------------------------------

    async def _graphql(
        self, document: str, variables: dict[str, Any], *, authenticated: bool = False
    ) -> dict[str, Any] | None:
        """POST one of the pinned documents. Retries once if the token was stale."""
        headers: dict[str, str] = {}
        if authenticated:
            headers["Authorization"] = f"Bearer {await self._tokens.get_access_token()}"
        payload = {"query": document, "variables": variables}
        data, errors = await self._graphql_once(payload, headers)
        if errors and _is_auth_error(errors) and authenticated:
            self._tokens.invalidate()
            headers["Authorization"] = f"Bearer {await self._tokens.get_access_token()}"
            data, errors = await self._graphql_once(payload, headers)
        if errors:
            message = _first_message(errors)
            if _is_auth_error(errors) and not self._settings.has_credentials:
                raise BoardseshAPIError(
                    "That needs your Boardsesh login. Add BOARDSESH_EMAIL and "
                    "BOARDSESH_PASSWORD to the boardsesh-mcp entry in your MCP config."
                )
            raise BoardseshAPIError(f"Boardsesh API error: {redact(message)}")
        return data

    async def _graphql_once(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        response = await self._request("POST", GRAPHQL_URL, json=payload, headers=headers)
        try:
            body = response.json()
        except ValueError:
            raise BoardseshAPIError(
                "Boardsesh returned non-JSON content for a GraphQL call."
            ) from None
        if not isinstance(body, dict):
            raise BoardseshAPIError("Boardsesh returned an unexpected GraphQL response.")
        errors = body.get("errors") or []
        return body.get("data"), [e for e in errors if isinstance(e, dict)]

    async def _get_json(self, url: str, *, params: dict[str, Any]) -> Any:
        response = await self._request("GET", url, params=params)
        try:
            return response.json()
        except ValueError:
            raise BoardseshAPIError(f"Boardsesh returned non-JSON content for {url}.") from None

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx2.Response:
        """Send a request, honouring 429 + Retry-After a bounded number of times."""
        retries = 0
        while True:
            try:
                response = await self._http.request(
                    method, url, timeout=self._settings.timeout_seconds, **kwargs
                )
            except AuthError:
                raise
            except httpx2.HTTPError as exc:
                raise BoardseshAPIError(
                    f"Network error talking to Boardsesh: {redact(str(exc))}"
                ) from None
            if response.status_code != 429 or retries >= self._max_rate_limit_retries:
                break
            delay = _retry_after_seconds(response)
            if delay is None or delay > self._max_retry_after_seconds:
                break
            await self._sleep(delay)
            retries += 1
        if response.status_code == 429:
            raise BoardseshAPIError(
                "Boardsesh is rate-limiting requests right now. Wait a minute and try again."
            )
        if response.status_code >= 400:
            raise BoardseshAPIError(
                f"Boardsesh request failed with HTTP {response.status_code} for {url}."
            )
        return response


def _first_message(errors: list[dict[str, Any]]) -> str:
    for error in errors:
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    return "unknown error"


def _is_auth_error(errors: list[dict[str, Any]]) -> bool:
    """Boardsesh answers an expired token with a resolver error, not a 401."""
    return any(AUTH_ERROR_MARKER in str(e.get("message", "")).lower() for e in errors)


def _retry_after_seconds(response: httpx2.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return float(raw)
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
