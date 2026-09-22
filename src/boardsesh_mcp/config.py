"""Settings read from the environment that the MCP client passes to this process.

Two tiers:

* ``BOARDSESH_USER`` alone (a display name or user id) is enough for everything Boardsesh
  serves publicly, which is most of the logbook. No secret required.
* ``BOARDSESH_EMAIL`` + ``BOARDSESH_PASSWORD`` additionally unlock the viewer-only extras:
  your own tick rows with vote/comment counts, your saved boards, personal-progress filters
  on climb search, and the personalised hold heatmap.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

USER_VAR = "BOARDSESH_USER"
EMAIL_VAR = "BOARDSESH_EMAIL"
PASSWORD_VAR = "BOARDSESH_PASSWORD"
TIMEZONE_VAR = "BOARDSESH_TIMEZONE"

MISSING_CONFIG_MESSAGE = (
    "Boardsesh is not configured. Set BOARDSESH_USER to your Boardsesh display name (or user "
    'id) in the "env" section of the boardsesh-mcp entry in your MCP config. Optionally add '
    "BOARDSESH_EMAIL and BOARDSESH_PASSWORD to unlock your private data (own tick details, "
    "saved boards, personalised hold heatmap)."
)

# A Boardsesh user id is a UUID; anything else is treated as a display name to look up.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    user: str
    email: str | None = None
    password: str | None = field(default=None, repr=False)
    timeout_seconds: float = 30.0

    def __repr__(self) -> str:  # never print the password
        creds = "with credentials" if self.has_credentials else "public only"
        return f"Settings(user={self.user!r}, {creds})"

    @property
    def has_credentials(self) -> bool:
        return bool(self.email and self.password)

    @property
    def user_is_id(self) -> bool:
        return bool(_UUID_RE.match(self.user))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        user = (source.get(USER_VAR) or "").strip()
        email = (source.get(EMAIL_VAR) or "").strip() or None
        password = source.get(PASSWORD_VAR) or None
        if not user:
            raise ConfigError(MISSING_CONFIG_MESSAGE)
        if bool(email) != bool(password):
            raise ConfigError(
                "Set both BOARDSESH_EMAIL and BOARDSESH_PASSWORD, or neither. With neither, "
                "public data still works."
            )
        return cls(user=user, email=email, password=password)


def resolve_timezone(env: Mapping[str, str] | None = None) -> tzinfo:
    """Timezone used to decide which calendar day a climb belongs to.

    Order: ``BOARDSESH_TIMEZONE`` (IANA name), then the host zone (``TZ``, then the
    ``/etc/localtime`` symlink), then the host's current fixed UTC offset.
    """
    source = os.environ if env is None else env
    explicit = (source.get(TIMEZONE_VAR) or "").strip()
    if explicit:
        try:
            return ZoneInfo(explicit)
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigError(
                f"{TIMEZONE_VAR}={explicit!r} is not a valid IANA timezone name "
                "(examples: Europe/Rome, America/Denver, UTC)."
            ) from None
    for candidate in (_tz_from_env(source), _tz_from_localtime()):
        if candidate is not None:
            return candidate
    return datetime.now().astimezone().tzinfo or timezone.utc


def timezone_name(tz: tzinfo) -> str:
    key = getattr(tz, "key", None)
    if isinstance(key, str):
        return key
    return tz.tzname(datetime.now(tz)) or "UTC"


def _tz_from_env(source: Mapping[str, str]) -> tzinfo | None:
    name = (source.get("TZ") or "").strip().lstrip(":")
    if not name or ("/" not in name and name.upper() != "UTC"):
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _tz_from_localtime() -> tzinfo | None:
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return None
    marker = "zoneinfo/"
    idx = target.rfind(marker)
    if idx == -1:
        return None
    try:
        return ZoneInfo(target[idx + len(marker) :])
    except (ZoneInfoNotFoundError, ValueError):
        return None


_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*")
_TOKEN_FIELD_RE = re.compile(
    r'(?i)("?(?:jwt|access_token|refreshToken|refresh_token|id_token|password)"?\s*[:=]\s*)'
    r'("?)[^",\s&}]+(\2)'
)


def redact(text: str, *secrets: str) -> str:
    """Remove bearer tokens, token/password fields and any given secret values from text."""
    out = _BEARER_RE.sub("Bearer ***", text)
    out = _TOKEN_FIELD_RE.sub(r"\1\2***\3", out)
    for secret in secrets:
        if secret:
            out = out.replace(secret, "***")
    return out
