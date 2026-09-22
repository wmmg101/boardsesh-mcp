"""All Boardsesh URLs in one place.

Boardsesh (https://www.boardsesh.com, Apache-2.0) documents a public API. The GraphQL endpoint
lives on the backend host; note the published docs page still advertises
``wss://boardsesh.com/api/graphql``, which does not exist. The real endpoints are below.
"""

from __future__ import annotations

WEB_BASE = "https://www.boardsesh.com"
BACKEND_BASE = "https://ws.boardsesh.com"

# GraphQL over plain HTTP POST. Accepts `Authorization: Bearer <token>` or no auth at all;
# many read queries are public.
GRAPHQL_URL = f"{BACKEND_BASE}/graphql"

# Headless email+password login used by the official mobile app. Returns a 7-day JWT plus a
# 90-day rotatable refresh token, so the password is never stored.
NATIVE_LOGIN_URL = f"{BACKEND_BASE}/auth/native/credentials"
NATIVE_REFRESH_URL = f"{BACKEND_BASE}/auth/native/refresh"
NATIVE_REVOKE_URL = f"{BACKEND_BASE}/auth/native/revoke"


# Hold heatmap is REST, not GraphQL, and returns JSON hold counts.
# /api/v1/{board}/{layout}/{size}/{sets}/{angle}/heatmap
def heatmap_url(board: str, layout_id: int, size_id: int, set_ids: str, angle: int) -> str:
    return f"{WEB_BASE}/api/v1/{board}/{layout_id}/{size_id}/{set_ids}/{angle}/heatmap"


# A plain User-Agent matters: Boardsesh's WAF blocks agentic crawler UAs
# (gptbot, claudebot, perplexitybot, ...) zone-wide.
USER_AGENT = "boardsesh-mcp (+https://github.com/wmmg101/boardsesh-mcp)"
