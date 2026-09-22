"""MCP server exposing read-only Boardsesh tools.

Tools are thin: parse arguments, fetch via ``BoardseshClient``, run pure analytics, return
structured data. No GraphQL strings or HTTP live here.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
import time
from collections.abc import Callable
from datetime import tzinfo
from typing import Annotated, Any, Literal, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from boardsesh_mcp import __version__, analytics
from boardsesh_mcp.auth import AuthError
from boardsesh_mcp.client import BoardConfig, BoardseshAPIError, BoardseshClient
from boardsesh_mcp.config import ConfigError, Settings, resolve_timezone, timezone_name
from boardsesh_mcp.grades import GradeTable
from boardsesh_mcp.models import Ascent

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)

# One question usually fans out into several tool calls; serve them from one logbook fetch.
LOGBOOK_CACHE_TTL_SECONDS = 60.0
# How much history to pull for whole-logbook analytics (feed pages are capped at 50 upstream).
LOGBOOK_PAGE_SIZE = 50
LOGBOOK_MAX_PAGES = 40

INSTRUCTIONS = (
    "Tools for one Boardsesh user's climbing logbook (read-only). Boardsesh aggregates logbooks "
    "across boards, so results span Kilter, Tension, MoonBoard, Decoy, Touchstone, So iLL, Woods "
    "and spray walls; every entry carries a 'board' field and most tools take an optional board "
    "filter. Use these whenever the user asks about their climbing: sessions, sends, flashes, "
    "projects, attempts, angles, grades, pyramids, progress, which board they are strongest on, "
    "what to try next, or which holds they avoid. "
    "'status' is 'flash' (sent first try), 'send' (sent after attempts) or 'attempt' (not sent); "
    "it is authoritative, so never infer it from try counts. 'grade' is the board's own grade; "
    "'boardsesh_grade' is a cross-board normalised number that makes boards comparable, and is "
    "null when not backed by real ascents. 'difficulty_id' is the raw id for filtering. Dates and "
    "sessions use the user's timezone, reported in the 'timezone' field."
)

_F = TypeVar("_F", bound=Callable[..., Any])

Board = Annotated[
    str | None,
    Field(
        description=(
            "Board type to filter to: kilter, tension, moonboard, decoy, touchstone, soill, "
            "grasshopper, woods or spray. Omit for all boards."
        )
    ),
]
Limit = Annotated[int | None, Field(description="Maximum number of items to return.", ge=1)]
StartDate = Annotated[
    str | None, Field(description="Inclusive start date, YYYY-MM-DD, in the user's timezone.")
]
EndDate = Annotated[
    str | None, Field(description="Inclusive end date, YYYY-MM-DD, in the user's timezone.")
]
Angle = Annotated[
    int | None, Field(description="Wall angle in degrees (e.g. 20, 40). Omit for all angles.")
]
Period = Annotated[
    Literal["month", "week"],
    Field(description="Bucket size for the progression: calendar month or ISO week."),
]


def _read_only_tool(server: MCPServer, name: str) -> Callable[[_F], _F]:
    """Register ``fn`` as a read-only tool whose description is its dedented docstring."""

    def decorator(fn: _F) -> _F:
        return server.tool(
            name=name, description=inspect.cleandoc(fn.__doc__ or ""), annotations=READ_ONLY
        )(fn)

    return decorator


class BoardseshService:
    """Owns the client for the process, caches the logbook, and makes failures safe to show."""

    def __init__(
        self,
        client_factory: Any = None,
        *,
        cache_ttl: float = LOGBOOK_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        tz: tzinfo | None = None,
    ) -> None:
        self._client_factory = client_factory or self._default_factory
        self._client: BoardseshClient | None = None
        self._cache_ttl = cache_ttl
        self._clock = clock
        self._tz = tz
        self._cached: tuple[list[Ascent], int] | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def _default_factory() -> BoardseshClient:
        return BoardseshClient(Settings.from_env())

    @property
    def tz(self) -> tzinfo:
        if self._tz is None:
            try:
                self._tz = resolve_timezone()
            except ConfigError as exc:
                raise ToolError(str(exc)) from None
        return self._tz

    @property
    def tz_name(self) -> str:
        return timezone_name(self.tz)

    def client(self) -> BoardseshClient:
        if self._client is None:
            try:
                self._client = self._client_factory()
            except ConfigError as exc:
                raise ToolError(str(exc)) from None
        return self._client

    async def logbook(self) -> tuple[list[Ascent], int]:
        """The user's whole logbook across every board, cached briefly."""
        client = self.client()
        async with self._lock:
            now = self._clock()
            if self._cached is not None and now - self._cached_at < self._cache_ttl:
                return self._cached
            try:
                ascents, total = await client.get_all_ascents(
                    page_size=LOGBOOK_PAGE_SIZE, max_pages=LOGBOOK_MAX_PAGES
                )
            except (AuthError, BoardseshAPIError) as exc:
                raise ToolError(str(exc)) from None
            self._cached = (ascents, total)
            self._cached_at = now
            return self._cached

    async def grades_for(self, boards: set[str]) -> dict[str, GradeTable]:
        client = self.client()
        out: dict[str, GradeTable] = {}
        for board in sorted(boards):
            try:
                out[board] = await client.get_grades(board)
            except (AuthError, BoardseshAPIError):
                continue
        return out

    async def grades_one(self, board: str | None) -> GradeTable | None:
        if board is None:
            return None
        tables = await self.grades_for({board})
        return tables.get(board)

    def envelope(self, body: dict[str, Any], *, total: int | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {"timezone": self.tz_name}
        if total is not None:
            out["total_entries"] = total
        out.update(body)
        return out

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _check_limit(limit: int | None, default: int, maximum: int = 200) -> int:
    if limit is None:
        return default
    if limit < 1:
        raise ToolError("limit must be a positive integer.")
    return min(limit, maximum)


def _filter(
    ascents: list[Ascent],
    *,
    board: str | None = None,
    angle: int | None = None,
    start: str | None = None,
    end: str | None = None,
    tz: tzinfo,
) -> list[Ascent]:
    out = []
    for a in ascents:
        if board is not None and a.board != board:
            continue
        if angle is not None and a.angle != angle:
            continue
        day = a.local_date(tz)
        if start is not None and (day is None or day < start):
            continue
        if end is not None and (day is None or day > end):
            continue
        out.append(a)
    return sorted(
        out, key=lambda a: a.climbed_at.timestamp() if a.climbed_at else 0.0, reverse=True
    )


def _dates(start_date: str | None, end_date: str | None, tz: tzinfo) -> tuple[Any, Any]:
    try:
        return analytics.parse_date_arg(start_date, tz=tz), analytics.parse_date_arg(
            end_date, tz=tz
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from None


async def _resolve_board_config(
    svc: BoardseshService, board: str | None, angle: int | None
) -> BoardConfig:
    """Find a board configuration for catalogue/heatmap queries.

    Needs all five coordinates (board, layout, size, sets, angle). With credentials we can read
    the user's saved boards; without them the user must be specific.
    """
    client = svc.client()
    if not client.authenticated:
        raise ToolError(
            "This needs to know which physical board setup to use (layout, size, hold sets). "
            "Add BOARDSESH_EMAIL and BOARDSESH_PASSWORD so your saved Boardsesh boards can be "
            "read, then ask again."
        )
    try:
        default, boards = await client.get_my_boards()
    except (AuthError, BoardseshAPIError) as exc:
        raise ToolError(str(exc)) from None
    candidates = [b for b in ([default] if default else []) + boards if b]
    if board is not None:
        candidates = [b for b in candidates if b.board == board]
    if not candidates:
        raise ToolError(
            "No saved Boardsesh board matches that request. Save the board you climb on in "
            "Boardsesh, or ask without a board filter."
        )
    chosen = candidates[0]
    if angle is not None and angle != chosen.angle:
        chosen = BoardConfig(
            board=chosen.board,
            layout_id=chosen.layout_id,
            size_id=chosen.size_id,
            set_ids=chosen.set_ids,
            angle=angle,
            name=chosen.name,
            layout_name=chosen.layout_name,
            size_name=chosen.size_name,
            uuid=chosen.uuid,
        )
    return chosen


def create_server(service: BoardseshService | None = None) -> MCPServer:
    svc = service or BoardseshService()
    server = MCPServer(
        name="boardsesh",
        title="Boardsesh climbing logbook",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/wmmg101/boardsesh-mcp",
    )

    @_read_only_tool(server, "boardsesh_get_summary")
    async def boardsesh_get_summary() -> dict[str, Any]:
        """Return a compact overview of the user's whole Boardsesh history, across all boards.

        Use first for broad questions ("how is my climbing going?", "summarise my logbook") or
        when you need totals: entries, sends, flashes, tries, boards used, angles, date range,
        session count, hardest send and flash, and sends per grade.
        """
        ascents, total = await svc.logbook()
        grades = await svc.grades_one(_dominant_board(ascents))
        body = analytics.summary(ascents, grades, tz=svc.tz, total_count=total)
        client = svc.client()
        try:
            counts = await client.get_tick_counts()
            body["ticks_per_board"] = [{"board": c.board, "count": c.count} for c in counts]
        except (AuthError, BoardseshAPIError):
            pass
        return svc.envelope(body, total=total)

    @_read_only_tool(server, "boardsesh_get_ascents")
    async def boardsesh_get_ascents(
        limit: Limit = 25,
        board: Board = None,
        angle: Angle = None,
        status: Annotated[
            Literal["all", "sends", "attempts", "flashes"] | None,
            Field(description="Filter by outcome. 'sends' includes flashes."),
        ] = "all",
        start_date: StartDate = None,
        end_date: EndDate = None,
    ) -> dict[str, Any]:
        """Return the user's logbook entries, newest first, across every board.

        Use when the user asks about recent climbs, sends, flashes, attempts, what they did on a
        date, or wants raw history. Each entry is one climb at one angle on one board at one time
        with the number of tries. Filters: limit (default 25), board, angle, status
        ('all', 'sends', 'attempts', 'flashes'), start_date/end_date (YYYY-MM-DD).
        """
        n = _check_limit(limit, 25)
        start, end = _dates(start_date, end_date, svc.tz)
        ascents, total = await svc.logbook()
        rows = _filter(ascents, board=board, angle=angle, start=start, end=end, tz=svc.tz)
        if status == "sends":
            rows = [a for a in rows if a.topped]
        elif status == "flashes":
            rows = [a for a in rows if a.status == "flash"]
        elif status == "attempts":
            rows = [a for a in rows if not a.topped]
        tables = await svc.grades_for({a.board for a in rows[:n]})
        return svc.envelope(
            {
                "matching": len(rows),
                "returned": min(n, len(rows)),
                "entries": [
                    analytics.ascent_to_dict(a, tables.get(a.board), svc.tz) for a in rows[:n]
                ],
            },
            total=total,
        )

    @_read_only_tool(server, "boardsesh_get_sessions")
    async def boardsesh_get_sessions(limit: Limit = 5, board: Board = None) -> dict[str, Any]:
        """Return recent climbing sessions (entries grouped by calendar day), newest first.

        Use when the user asks how their last session went, what they climbed on a day, or wants
        to compare sessions. Each session lists the boards and angles used, sends, flashes, total
        tries, hardest send and every climb logged that day.
        """
        n = _check_limit(limit, 5, maximum=60)
        ascents, total = await svc.logbook()
        rows = _filter(ascents, board=board, tz=svc.tz)
        grades = await svc.grades_one(board or _dominant_board(rows))
        return svc.envelope(
            {"sessions": analytics.sessions(rows, grades, limit=n, tz=svc.tz)}, total=total
        )

    @_read_only_tool(server, "boardsesh_get_projects")
    async def boardsesh_get_projects(limit: Limit = 25, board: Board = None) -> dict[str, Any]:
        """Return the user's projects: climbs attempted but never sent at that angle.

        Use when the user asks what they are working on, unfinished climbs, or what to try again.
        A project is per (board, climb, angle), so sending a climb at another angle does not
        remove it. Sorted by most recently tried, then most tries.
        """
        n = _check_limit(limit, 25)
        ascents, total = await svc.logbook()
        rows = _filter(ascents, board=board, tz=svc.tz)
        grades = await svc.grades_one(board or _dominant_board(rows))
        found = analytics.projects(rows, grades, tz=svc.tz)
        return svc.envelope(
            {"matching": len(found), "returned": min(n, len(found)), "projects": found[:n]},
            total=total,
        )

    @_read_only_tool(server, "boardsesh_compare_boards")
    async def boardsesh_compare_boards() -> dict[str, Any]:
        """Compare the user's climbing across every board they have logged on.

        Use when the user asks which board they are strongest on, how Kilter compares with
        Tension or MoonBoard, or where they climb most. One row per board with sends, flashes,
        flash rate, tries, sessions, angles, hardest send in that board's own grades, and
        'hardest_boardsesh_grade' / 'median_boardsesh_grade' which are normalised across boards
        and therefore the fair comparison.
        """
        ascents, total = await svc.logbook()
        tables = await svc.grades_for({a.board for a in ascents})
        rows = analytics.board_comparison(ascents, tables, tz=svc.tz)
        return svc.envelope(
            {
                "boards": rows,
                "note": (
                    "Board-native grades are not comparable between boards (MoonBoard grades "
                    "hard, Kilter soft). Use the boardsesh_grade numbers to compare."
                ),
            },
            total=total,
        )

    @_read_only_tool(server, "boardsesh_get_grade_pyramid")
    async def boardsesh_get_grade_pyramid(board: Board = None) -> dict[str, Any]:
        """Return the user's send pyramid: sends per grade, hardest first, with flash rates.

        Use when the user asks about their pyramid, grade distribution, flash rate per grade, or
        how solid they are at a level. Optional board filter; grades differ between boards, so
        prefer filtering to one board when the user names one.
        """
        ascents, total = await svc.logbook()
        grades = await svc.grades_one(board or _dominant_board(ascents))
        return svc.envelope(analytics.grade_pyramid(ascents, grades, board=board), total=total)

    @_read_only_tool(server, "boardsesh_get_progression")
    async def boardsesh_get_progression(
        period: Period = "month", board: Board = None
    ) -> dict[str, Any]:
        """Return climbing progression over time, oldest period first.

        Use when the user asks whether they are improving, about trends, or for a month-by-month
        or week-by-week view. Each period has sessions, boards used, entries, sends, unique
        climbs, flashes, tries and the hardest send.
        """
        ascents, total = await svc.logbook()
        rows = _filter(ascents, board=board, tz=svc.tz)
        grades = await svc.grades_one(board or _dominant_board(rows))
        try:
            periods = analytics.progression(rows, grades, period=period, tz=svc.tz)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        return svc.envelope({"period": period, "periods": periods}, total=total)

    @_read_only_tool(server, "boardsesh_recommend_climbs")
    async def boardsesh_recommend_climbs(
        kind: Annotated[
            Literal["at_level", "crowd_favorites", "hidden_gems", "fresh"],
            Field(
                description=(
                    "'at_level' picks climbs around the user's current grade, "
                    "'crowd_favorites' popular ones, 'hidden_gems' under-climbed ones, "
                    "'fresh' recently set ones."
                )
            ),
        ] = "at_level",
        board: Board = None,
        angle: Angle = None,
        limit: Limit = 15,
    ) -> dict[str, Any]:
        """Suggest climbs the user has not sent yet, from Boardsesh's recommendations.

        Use when the user asks what to try next, wants new climbs, projects at their level, or
        something fresh. 'at_level' works from their own send history and excludes climbs they
        have already sent. Needs a board configuration, so it uses one of the user's saved
        Boardsesh boards.
        """
        n = _check_limit(limit, 15, maximum=100)
        config = await _resolve_board_config(svc, board, angle)
        playlist_type = {
            "at_level": "RECOMMENDED_AT_LEVEL",
            "crowd_favorites": "RECOMMENDED_CROWD_FAVORITES",
            "hidden_gems": "RECOMMENDED_HIDDEN_GEMS",
            "fresh": "RECOMMENDED_FRESH",
        }[kind]
        client = svc.client()
        try:
            result = await client.get_smart_playlist(
                playlist_type,
                boardName=config.board,
                sizeId=config.size_id,
                angle=config.angle,
                pageSize=n,
            )
        except (AuthError, BoardseshAPIError) as exc:
            raise ToolError(str(exc)) from None
        return svc.envelope(
            {
                "kind": kind,
                "board_config": config.to_dict(),
                "matching": result["total_count"],
                "climbs": [_climb_dict(c) for c in result["climbs"][:n]],
            }
        )

    @_read_only_tool(server, "boardsesh_find_similar_climbs")
    async def boardsesh_find_similar_climbs(
        climb_uuid: Annotated[
            str,
            Field(
                description=(
                    "The climb to match, as a climb_uuid from another tool's output "
                    "(e.g. a send or project)."
                )
            ),
        ],
        board: Board = None,
        angle: Angle = None,
        limit: Limit = 10,
    ) -> dict[str, Any]:
        """Find climbs that use a similar set of holds to a given climb.

        Use when the user asks for climbs like one they enjoyed or one they are projecting, or
        wants to train a specific movement again. Similarity is hold overlap (0-1); 0.5 and above
        feels genuinely related. Pass a climb_uuid from an earlier result.
        """
        n = _check_limit(limit, 10, maximum=50)
        config = await _resolve_board_config(svc, board, angle)
        client = svc.client()
        try:
            climbs = await client.similar_climbs(
                boardType=config.board,
                layoutId=config.layout_id,
                sizeId=config.size_id,
                angle=config.angle,
                climbUuid=climb_uuid,
                threshold=0.5,
                limit=n,
                excludeClimbUuid=climb_uuid,
            )
        except (AuthError, BoardseshAPIError) as exc:
            raise ToolError(str(exc)) from None
        return svc.envelope(
            {"board_config": config.to_dict(), "climbs": [_climb_dict(c) for c in climbs]}
        )

    @_read_only_tool(server, "boardsesh_get_hold_heatmap")
    async def boardsesh_get_hold_heatmap(
        board: Board = None,
        angle: Angle = None,
        min_grade_id: Annotated[
            int | None,
            Field(description="Only count climbs at or above this difficulty_id."),
        ] = None,
        max_grade_id: Annotated[
            int | None,
            Field(description="Only count climbs at or below this difficulty_id."),
        ] = None,
        only_my_projects: Annotated[
            bool | None,
            Field(
                description=(
                    "Restrict to climbs the user has attempted but not completed, to see which "
                    "holds show up in their unfinished projects."
                )
            ),
        ] = None,
        limit: Limit = 15,
    ) -> dict[str, Any]:
        """Return which holds the wall's climbs use, for spotting strengths and weaknesses.

        Use when the user asks about weaknesses, hold types they avoid or overuse, or what to
        train. Returns per-hold counts (how many climbs use each hold, and whether as hand, foot,
        start or finish) plus the average difficulty of climbs using it. Combine with a grade
        range to ask "which holds appear in climbs at my next grade". Hold ids are wall positions;
        reason about patterns and grade ranges rather than individual ids.
        """
        n = _check_limit(limit, 15, maximum=60)
        config = await _resolve_board_config(svc, board, angle)
        params: dict[str, Any] = {}
        if min_grade_id is not None:
            params["minGrade"] = min_grade_id
        if max_grade_id is not None:
            params["maxGrade"] = max_grade_id
        if only_my_projects:
            params["showOnlyAttempted"] = "true"
            params["hideCompleted"] = "true"
        client = svc.client()
        try:
            holds = await client.get_hold_heatmap(config, params=params)
        except (AuthError, BoardseshAPIError) as exc:
            raise ToolError(str(exc)) from None
        body = analytics.hold_usage(holds, limit=n)
        body["board_config"] = config.to_dict()
        body["filters"] = params or None
        return svc.envelope(body)

    @_read_only_tool(server, "boardsesh_search_climbs")
    async def boardsesh_search_climbs(
        name: Annotated[str | None, Field(description="Match part of a climb name.")] = None,
        board: Board = None,
        angle: Angle = None,
        min_grade_id: Annotated[
            int | None, Field(description="Minimum difficulty_id (see boardsesh_get_grades).")
        ] = None,
        max_grade_id: Annotated[int | None, Field(description="Maximum difficulty_id.")] = None,
        exclude_sent: Annotated[
            bool | None,
            Field(description="Hide climbs the user has already sent at this angle."),
        ] = None,
        only_benchmarks: Annotated[bool | None, Field(description="Only benchmark climbs.")] = None,
        min_ascents: Annotated[
            int | None, Field(description="Only climbs with at least this many community ascents.")
        ] = None,
        limit: Limit = 20,
    ) -> dict[str, Any]:
        """Search the board's climb catalogue with filters.

        Use when the user wants to find specific climbs: by name, grade range, benchmarks only,
        popularity, or excluding ones they have already sent. For "what should I try next" prefer
        boardsesh_recommend_climbs, which uses the user's own level.
        """
        n = _check_limit(limit, 20, maximum=100)
        config = await _resolve_board_config(svc, board, angle)
        client = svc.client()
        try:
            result = await client.search_climbs(
                boardName=config.board,
                layoutId=config.layout_id,
                sizeId=config.size_id,
                setIds=config.set_ids,
                angle=config.angle,
                name=name,
                minGrade=min_grade_id,
                maxGrade=max_grade_id,
                hideCompleted=exclude_sent,
                onlyBenchmarks=only_benchmarks,
                minAscents=min_ascents,
                pageSize=n,
                sortBy="ascents",
            )
        except (AuthError, BoardseshAPIError) as exc:
            raise ToolError(str(exc)) from None
        return svc.envelope(
            {
                "board_config": config.to_dict(),
                "matching": result["total_count"],
                "climbs": [_climb_dict(c) for c in result["climbs"][:n]],
            }
        )

    @_read_only_tool(server, "boardsesh_get_grades")
    async def boardsesh_get_grades(
        board: Annotated[
            str, Field(description="Board type, e.g. kilter, tension, moonboard.")
        ] = "kilter",
    ) -> dict[str, Any]:
        """Return a board's grade scale: difficulty_id to grade label.

        Use when you need a difficulty_id for a grade the user named (e.g. to pass min_grade_id
        to a search), or to explain what a grade id means. Boards do not share one scale.
        """
        client = svc.client()
        try:
            table = await client.get_grades(board)
        except (AuthError, BoardseshAPIError) as exc:
            raise ToolError(str(exc)) from None
        return svc.envelope(
            {
                "board": board,
                "source": table.source,
                "grades": [
                    {"difficulty_id": g.id, "grade": g.label, "v_grade": g.v_scale}
                    for g in sorted(table.grades.values(), key=lambda g: g.id)
                ],
            }
        )

    return server


def _dominant_board(ascents: list[Ascent]) -> str | None:
    """The board with the most entries, used to pick one grade table for mixed output."""
    counts: dict[str, int] = {}
    for a in ascents:
        counts[a.board] = counts.get(a.board, 0) + 1
    return max(counts, key=lambda b: counts[b]) if counts else None


def _climb_dict(climb: Any) -> dict[str, Any]:
    out = {
        "name": climb.name,
        "board": climb.board,
        "angle": climb.angle,
        "grade": climb.difficulty_name,
        "community_ascents": climb.ascents,
        "quality": climb.quality,
        "setter": climb.setter,
        "benchmark": climb.benchmark,
        "my_sends": climb.user_ascents,
        "my_tries": climb.user_attempts,
        "climb_uuid": climb.climb_uuid,
    }
    if climb.similarity is not None:
        out["similarity"] = round(climb.similarity, 3)
    return out


HELP = (
    f"boardsesh-mcp {__version__} - unofficial MCP server for your Boardsesh climbing logbook.\n\n"
    "Speaks MCP over stdio; meant to be launched by an MCP client such as Kiro or Claude, not\n"
    "run by hand. Configure BOARDSESH_USER (your Boardsesh display name or user id) in the env\n"
    "section of your MCP config. Optionally add BOARDSESH_EMAIL and BOARDSESH_PASSWORD to\n"
    "unlock your saved boards, recommendations and the hold heatmap.\n"
    "See https://github.com/wmmg101/boardsesh-mcp\n\n"
    "Options:\n"
    "  --check     Resolve the user, fetch the logbook and print a short diagnostic\n"
    "              (no entries, no secrets). Exit code 0 on success.\n"
    "  --version   Print the version.\n"
)


async def run_check(service: BoardseshService | None = None) -> tuple[int, str]:
    """Diagnostic for ``boardsesh-mcp --check``. Prints counts only, never entries or secrets."""
    svc = service or BoardseshService()
    lines = [f"boardsesh-mcp {__version__}"]
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        return 1, "\n".join([*lines, f"config:    FAILED - {exc}"])
    mode = "public + credentials" if settings.has_credentials else "public only"
    lines.append(f"config:    ok ({mode})")
    client = svc.client()
    try:
        lines.append(f"timezone:  {svc.tz_name}")
        user_id, display = await client.resolve_user()
        lines.append(f"user:      {display or '(no display name)'} [{user_id[:8]}...]")
        counts = await client.get_tick_counts()
        lines.append(
            "boards:    "
            + (", ".join(f"{c.board}={c.count}" for c in counts) if counts else "none logged")
        )
        ascents, total = await svc.logbook()
        days = {d for d in (a.local_date(svc.tz) for a in ascents) if d}
        lines.append(
            f"logbook:   {len(ascents)} loaded of {total} entries, "
            f"{sum(1 for a in ascents if a.topped)} sends, {len(days)} sessions, "
            f"most recent {max(days) if days else 'n/a'}"
        )
        if settings.has_credentials:
            default, boards = await client.get_my_boards()
            lines.append(
                f"my boards: {len(boards)} saved, default "
                + (
                    f"{default.board} ({default.layout_name or default.layout_id})"
                    if default
                    else "none"
                )
            )
    except (AuthError, BoardseshAPIError, ToolError) as exc:
        return 1, "\n".join([*lines, f"boardsesh: FAILED - {exc}"])
    finally:
        await svc.aclose()
    lines.append("result:    ok")
    return 0, "\n".join(lines)


def quiet_http_logging() -> None:
    """Keep the HTTP client from logging request URLs.

    Stdio MCP servers share the terminal with their client, and request URLs carry the
    user id. Warnings and errors still come through.
    """
    for name in ("httpx2", "httpx", "httpcore2", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> None:
    """Console entry point: ``boardsesh-mcp``."""
    args = sys.argv[1:] if argv is None else argv
    quiet_http_logging()
    if any(a in ("-h", "--help") for a in args):
        sys.stdout.write(HELP)
        return
    if any(a in ("-V", "--version") for a in args):
        sys.stdout.write(f"boardsesh-mcp {__version__}\n")
        return
    if "--check" in args:
        code, report = asyncio.run(run_check())
        sys.stdout.write(report + "\n")
        sys.exit(code)
    server = create_server()
    try:
        server.run("stdio")
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
