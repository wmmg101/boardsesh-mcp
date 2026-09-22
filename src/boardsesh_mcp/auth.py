"""Optional Boardsesh authentication.

Only needed for viewer-only data. Uses the headless email+password endpoint the official mobile
app uses, which returns a short-lived access JWT plus a rotatable refresh token, so the password
is exchanged once and never stored anywhere but this process's memory.

Nothing here is ever logged, and error text is redacted before it leaves.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx2

from boardsesh_mcp.config import Settings, redact
from boardsesh_mcp.endpoints import NATIVE_LOGIN_URL, NATIVE_REFRESH_URL, USER_AGENT

# Refresh this many seconds before the access token actually expires.
EXPIRY_MARGIN_SECONDS = 120.0
# Assumed access-token lifetime if the server doesn't say (it currently issues 7 days).
DEFAULT_LIFETIME_SECONDS = 7 * 24 * 3600.0
# After a rejected login, wait before trying again. Boardsesh rate-limits login per IP with a
# bucket shared across clients behind their proxy, so retry storms hurt everyone.
LOGIN_FAILURE_COOLDOWN_SECONDS = 120.0


class AuthError(RuntimeError):
    """Boardsesh authentication failed. Message is safe to show to the agent.

    ``rejected`` is True when Boardsesh answered and refused the credentials, as opposed to a
    network failure, a rate limit, or a server error.
    """

    def __init__(self, message: str, *, rejected: bool = False) -> None:
        super().__init__(message)
        self.rejected = rejected


class TokenManager:
    """Holds the access/refresh tokens in memory for the process lifetime."""

    def __init__(
        self,
        settings: Settings,
        http: httpx2.AsyncClient,
        *,
        clock: Callable[[], float] = time.monotonic,
        login_failure_cooldown: float = LOGIN_FAILURE_COOLDOWN_SECONDS,
    ) -> None:
        self._settings = settings
        self._http = http
        self._clock = clock
        self._cooldown = login_failure_cooldown
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at = 0.0
        self._blocked_until = 0.0
        self._last_error: str | None = None

    def __repr__(self) -> str:
        return f"TokenManager({'authenticated' if self._access_token else 'unauthenticated'})"

    def _redact(self, text: str) -> str:
        return redact(
            text,
            self._settings.password or "",
            self._access_token or "",
            self._refresh_token or "",
        )

    async def get_access_token(self) -> str:
        """Return a valid access token, logging in or refreshing as needed."""
        if not self._settings.has_credentials:
            raise AuthError(
                "This needs your Boardsesh login. Add BOARDSESH_EMAIL and BOARDSESH_PASSWORD "
                "to the boardsesh-mcp entry in your MCP config, or ask for something that only "
                "uses public data."
            )
        if self._access_token and self._clock() < self._expires_at - EXPIRY_MARGIN_SECONDS:
            return self._access_token
        if self._refresh_token:
            try:
                await self._refresh()
                assert self._access_token is not None
                return self._access_token
            except AuthError:
                self._refresh_token = None
        await self._login()
        assert self._access_token is not None
        return self._access_token

    def invalidate(self) -> None:
        """Force a refresh on the next call (e.g. after an auth error from the API)."""
        self._expires_at = 0.0

    async def _login(self) -> None:
        now = self._clock()
        if self._last_error is not None and now < self._blocked_until:
            raise AuthError(
                f"{self._last_error} Not retrying for "
                f"{int(self._blocked_until - now) + 1}s; fix the credentials and try again."
            )
        try:
            await self._token_request(
                NATIVE_LOGIN_URL,
                {"email": self._settings.email, "password": self._settings.password},
                failure_hint=(
                    "Boardsesh login failed. Check BOARDSESH_EMAIL and BOARDSESH_PASSWORD in "
                    "your MCP configuration."
                ),
            )
        except AuthError as exc:
            if exc.rejected:
                self._last_error = str(exc)
                self._blocked_until = self._clock() + self._cooldown
            raise
        self._last_error = None
        self._blocked_until = 0.0

    async def _refresh(self) -> None:
        await self._token_request(
            NATIVE_REFRESH_URL,
            {"refreshToken": self._refresh_token},
            failure_hint="Boardsesh token refresh failed.",
        )

    async def _token_request(self, url: str, payload: dict[str, Any], *, failure_hint: str) -> None:
        # Split in two so the frame holding the password never raises: pytest and debuggers
        # print the arguments of the failing frame.
        outcome = await self._post(url, payload)
        self._apply(outcome, failure_hint)

    async def _post(self, url: str, payload: dict[str, Any]) -> tuple[int, Any, str]:
        try:
            response = await self._http.post(
                url,
                json=payload,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                timeout=self._settings.timeout_seconds,
            )
        except httpx2.HTTPError as exc:
            return 0, None, self._redact(str(exc))
        try:
            return response.status_code, response.json(), ""
        except ValueError:
            return response.status_code, None, ""

    def _apply(self, outcome: tuple[int, Any, str], failure_hint: str) -> None:
        status, payload, network_error = outcome
        if status == 0:
            raise AuthError(f"{failure_hint} Network error: {network_error}")
        if status == 429:
            raise AuthError(
                f"{failure_hint} Boardsesh is rate-limiting logins right now; try again in a "
                "minute."
            )
        if status != 200:
            detail = ""
            if isinstance(payload, dict):
                message = payload.get("error") or payload.get("message")
                if isinstance(message, str):
                    detail = f": {message}"
            raise AuthError(
                f"{failure_hint} (HTTP {status}{detail})",
                rejected=status in (400, 401, 403),
            )
        if not isinstance(payload, dict):
            raise AuthError(f"{failure_hint} Unexpected non-JSON response.")

        token = payload.get("jwt") or payload.get("accessToken")
        if not isinstance(token, str) or not token:
            raise AuthError(f"{failure_hint} Response contained no access token.")
        self._access_token = token
        refresh = payload.get("refreshToken")
        if isinstance(refresh, str) and refresh:
            self._refresh_token = refresh
        self._expires_at = self._clock() + _lifetime_from(payload)


def _lifetime_from(payload: dict[str, Any]) -> float:
    """Seconds until the access token expires, from expiresAt or expiresIn if present."""
    expires_in = payload.get("expiresIn")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        return float(expires_in)
    expires_at = payload.get("expiresAt")
    if isinstance(expires_at, str):
        from boardsesh_mcp.models import parse_datetime

        parsed = parse_datetime(expires_at)
        if parsed is not None:
            from datetime import datetime, timezone

            remaining = (parsed - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                return remaining
    return DEFAULT_LIFETIME_SECONDS
