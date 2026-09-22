# boardsesh-mcp — Design

## Layers

```
agent → MCP (stdio) → server.py → analytics.py / grades.py → models.py
                                → client.py → auth.py, queries.py, endpoints.py
```

## Endpoints

- GraphQL HTTP POST at `https://ws.boardsesh.com/graphql`. Accepts `Authorization: Bearer` or no
  auth; most read queries are public and take a `userId`. (Boardsesh's published docs advertise
  `wss://boardsesh.com/api/graphql`, which does not exist — verified.)
- Login at `https://ws.boardsesh.com/auth/native/credentials` → `{jwt, refreshToken, expiresAt}`.
- Hold heatmap is REST: `/api/v1/{board}/{layout}/{size}/{sets}/{angle}/heatmap`, returning JSON
  per-hold counts. Its personal columns need a NextAuth cookie session, which this client does not
  use, so heatmaps are community-wide for now (see the open question below).

## Key decisions

- **Two tiers.** Public by default; credentials only for viewer-only data. This keeps the common
  setup secret-free.
- **Pinned documents.** `queries.py` is the complete set of operations; the client never accepts a
  document from a caller. This is the main defence against a confused or injected prompt reaching
  a mutation.
- **Whole-logbook analytics.** `BoardseshService` pages the feed once (cached 60s) and every
  aggregate tool works over that list in memory, so one question costs one fetch.
- **Grade handling.** Labels come from `grades(boardName:)` per board with an embedded Aurora
  fallback. `boardsesh_grade` is gated on confidence tier.
- **Board configuration.** Catalogue and heatmap queries need five coordinates
  (board, layout, size, sets, angle), which only the owner can read, hence those tools needing
  credentials. Resolved from `defaultBoard` then `myBoards`.

## Open questions

1. The heatmap's personal columns (`userAscents`/`userAttempts`) require a cookie session rather
   than the bearer token everything else accepts. Ask the Boardsesh maintainer whether the route
   can accept a bearer; otherwise reconstruct hold usage client-side from the logbook, which costs
   one request per climb.
2. `projectsOnly` in climb search means *community* zero-ascent, while `SmartPlaylistType.PROJECTS`
   means *the user's unsent*. Do not conflate them.
3. The heatmap's `totalAscents` changes meaning when a personal-progress filter is passed, with
   nothing in the response indicating which mode ran.
