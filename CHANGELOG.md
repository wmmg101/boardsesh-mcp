# Changelog

All notable changes to boardsesh-mcp. Versions follow [Semantic Versioning](https://semver.org).

## 0.1.0 - 2026-09-22

First release.

- Read-only MCP server over a Boardsesh climbing logbook, launched with `uvx boardsesh-mcp`.
- Multi-board: one logbook spanning Kilter, Tension, MoonBoard, Decoy, Touchstone, So iLL, Woods
  and spray walls, with `boardsesh_compare_boards` using Boardsesh's cross-board normalised grade
  so boards can actually be compared.
- Works with no secret: `BOARDSESH_USER` (a display name or user id) is enough for eight of the
  twelve tools, because Boardsesh serves logbook data publicly.
- Optional `BOARDSESH_EMAIL` / `BOARDSESH_PASSWORD` unlock recommendations, catalogue search,
  similar climbs and the hold heatmap, which need the user's saved board configuration.
- Tools: summary, ascents, sessions, projects, board comparison, grade pyramid, progression,
  grade scale, recommendations, search, similar climbs, hold heatmap.
- Only pinned GraphQL documents are ever sent, so no code path can reach a mutation.
- Tokens are in-memory only; credentials never appear in output, logs or errors.
