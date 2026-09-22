# boardsesh-mcp — Requirements

## Product

An MCP server giving an AI agent read-only access to one Boardsesh user's climbing logbook across
every board they use. The MCP server is the product.

## Functional

- R1. `BOARDSESH_USER` (display name or user id) is the only required configuration. A display
  name is resolved via the public user search; an exact case-insensitive match wins, and an
  ambiguous match is an actionable error listing candidates.
- R2. `BOARDSESH_EMAIL` + `BOARDSESH_PASSWORD` are optional and must be set together. They unlock
  viewer-only data; without them those tools fail with a message naming both variables.
- R3. `BOARDSESH_TIMEZONE` (IANA) overrides the host timezone used to group days.
- R4. Credentials are exchanged once for an access token plus refresh token, held in memory only,
  refreshed before expiry, and re-obtained if the refresh token is rejected. After a rejected
  login, wait before retrying.
- R5. An expired token surfaces as a resolver error rather than a 401; detect it and retry once.
- R6. Only pinned GraphQL documents are sent. No mutation is reachable.
- R7. The logbook is paged through the ascents feed (50 per page upstream) and cached for 60s;
  concurrent tool calls share one fetch.
- R8. HTTP 429 is retried after `Retry-After`, bounded, then reported clearly.
- R9. Tools: summary, ascents, sessions, projects, compare_boards, grade_pyramid, progression,
  grades (all public); recommend_climbs, search_climbs, find_similar_climbs, hold_heatmap
  (credentials).
- R10. All tools are read-only, declare `read_only_hint`, describe every argument, and return
  structured data including `timezone`.
- R11. `--check` prints a diagnostic with counts and configuration only: no entries, no secrets.

## Data semantics

- One entry = one climb, one angle, one board, one time, with a try count. Never deduplicated.
- `status` is authoritative: `flash` / `send` / `attempt`.
- Identity for grouping is `(board, climb_uuid, angle)`; a project is such a key with attempts
  and no send.
- Personal grade beats consensus. The ascents feed lacks `effectiveDifficulty`, so coalesce.
- Board-native grades are not comparable across boards; `boardsesh_grade` is, but only when its
  confidence tier is ascent-backed.
- A session is one calendar day in the user's timezone.

## Non-functional

- N1. Credentials and tokens never appear in output, logs, exceptions or fixtures.
- N2. Tests use mocked HTTP; CI needs no account.
- N3. Nothing user-specific is hardcoded.
- N4. Runs via `uvx boardsesh-mcp`; Python ≥ 3.10.
- N5. README leads with the no-password setup.

## Out of scope for 0.1

Writes of any kind, live session/queue features, spray wall management, social feeds, following,
playlists, gyms, and reading other climbers' logbooks.
