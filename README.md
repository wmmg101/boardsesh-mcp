# boardsesh-mcp

<!-- mcp-name: io.github.wmmg101/boardsesh-mcp -->

An unofficial [MCP](https://modelcontextprotocol.io) server that lets your AI agent read and
analyse **your [Boardsesh](https://www.boardsesh.com) climbing logbook** — across every board you
climb on: Kilter, Tension, MoonBoard, Decoy, Touchstone, So iLL, Woods and spray walls.

> How did my last session go?
> Am I stronger on Kilter or on Tension?
> What are my projects at 40°?
> What should I try next at my level?
> Show my grade pyramid. Which holds do I avoid?

Read-only. Nothing is ever written to your Boardsesh account.

**You do not need to give it a password.** Boardsesh serves your logbook publicly, so your
display name alone unlocks most of it. Credentials are optional and only add the extras.

## Add to your agent

### Kiro

Open your MCP config (command palette → **Kiro: Open user MCP config (JSON)**) and add:

```json
{
  "mcpServers": {
    "boardsesh": {
      "command": "uvx",
      "args": ["boardsesh-mcp"],
      "env": {
        "BOARDSESH_USER": "Your Boardsesh Display Name"
      },
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

That is the whole setup. `BOARDSESH_USER` is the display name on your Boardsesh profile (or your
user id, if you prefer). Requires [`uv`](https://docs.astral.sh/uv/) installed; `uvx` ships with
it.

### Other clients

Same three facts everywhere: command `uvx`, args `["boardsesh-mcp"]`, env `BOARDSESH_USER`.
Copy-paste configs for Claude Desktop, Claude Code, Codex, Cursor, VS Code, Windsurf, Gemini CLI
and Zed are in [docs/clients.md](docs/clients.md).

### Optional: unlock the rest

Four tools need to know which physical board setup you use (layout, size, hold sets), which
Boardsesh only tells the logged-in owner. Add your Boardsesh login to enable them:

```json
"env": {
  "BOARDSESH_USER": "Your Display Name",
  "BOARDSESH_EMAIL": "${BOARDSESH_EMAIL}",
  "BOARDSESH_PASSWORD": "${BOARDSESH_PASSWORD}"
}
```

Those four are `boardsesh_recommend_climbs`, `boardsesh_search_climbs`,
`boardsesh_find_similar_climbs` and `boardsesh_get_hold_heatmap`. Everything else works without
them. See [how to set environment variables](docs/clients.md#setting-the-environment-variables).

### Optional: timezone

Sessions are grouped by calendar day in your timezone, detected from the machine running the
server. If that is wrong, add `"BOARDSESH_TIMEZONE": "Europe/Rome"` (any IANA name).

## Example questions

```text
Summarise my Boardsesh logbook.
How did my last session go?
Compare my climbing on Kilter and Tension — where am I actually stronger?
What are my current projects, and which have I tried the most?
Show my grade pyramid and my flash rate per grade.
Have I improved over the last six months?
What should I try next at my level?
Find climbs similar to the one I sent yesterday.
Which holds show up most in climbs one grade above me?
```

## Tools the agent gets

Works with just `BOARDSESH_USER`:

| Tool | What it returns |
|---|---|
| `boardsesh_get_summary` | Totals across all boards: sends, flashes, sessions, date range, hardest send |
| `boardsesh_get_ascents` | Logbook entries, filterable by board, angle, outcome and date range |
| `boardsesh_get_sessions` | Entries grouped by day |
| `boardsesh_get_projects` | Climbs attempted but never sent, per board, climb and angle |
| `boardsesh_compare_boards` | One row per board, with cross-board normalised grades |
| `boardsesh_get_grade_pyramid` | Sends per grade with flash rates |
| `boardsesh_get_progression` | Month-by-month or week-by-week trend |
| `boardsesh_get_grades` | A board's grade scale (difficulty ids to labels) |

Needs `BOARDSESH_EMAIL` / `BOARDSESH_PASSWORD`:

| Tool | What it returns |
|---|---|
| `boardsesh_recommend_climbs` | Climbs to try next: at your level, crowd favourites, hidden gems, fresh |
| `boardsesh_search_climbs` | Catalogue search by name, grade range, benchmarks, popularity |
| `boardsesh_find_similar_climbs` | Climbs sharing holds with a given climb |
| `boardsesh_get_hold_heatmap` | Which holds the wall's climbs use, for spotting weaknesses |

## How the data is interpreted

- One logbook entry is one climb, at one angle, on one board, at one time, with a number of
  tries. Entries are never deduplicated, so a climb can appear many times.
- `status` is authoritative: `flash` (sent first try), `send` (sent after attempts) or `attempt`
  (not sent). It is never inferred from try counts.
- A project is a `(board, climb, angle)` you have attempted but not sent. Sending it at another
  angle does not remove it.
- `grade` is the board's own grade and `difficulty_id` the raw id. Board grades are **not**
  comparable between boards, so `boardsesh_grade` — Boardsesh's cross-board normalised number —
  is what `boardsesh_compare_boards` uses. It is null when Boardsesh's confidence in it is not
  backed by real ascents.
- A "session" is one calendar day in your timezone.

## Security and privacy

- In the default setup there is **no secret to leak**: only your public display name is
  configured, and everything it reads is what your Boardsesh profile already shows publicly.
- If you do add credentials, they are used once to obtain a token from Boardsesh's own login
  endpoint. Tokens live in memory for the life of the process and are never written to disk.
- Credentials and tokens never appear in tool output, logs or error messages.
- The server talks only to `ws.boardsesh.com` and `www.boardsesh.com`. No telemetry.
- Every tool is read-only, and the GraphQL layer can only send a fixed set of pinned read
  queries — there is no code path that could reach a mutation.
- Your logbook is fetched at most once a minute however many tools the agent calls.

Troubleshooting: run `uvx boardsesh-mcp --check` with the same environment variables set. It
prints counts and configuration only, no entries and no secrets, so it is safe to paste into an
issue.

## Relationship to Boardsesh and to kilter-mcp

[Boardsesh](https://github.com/boardsesh/boardsesh) is an open-source (Apache-2.0) board-climbing
app that aggregates logbooks across boards and publishes an API. This project is an independent
MCP client for it, built at the suggestion of its maintainer, but it is not an official Boardsesh
product and any bug here is mine, not theirs.

If you only climb on a Kilter Board and do not use Boardsesh,
[kilter-mcp](https://github.com/wmmg101/kilter-mcp) talks to Kilter directly instead. boardsesh-mcp
is the better choice if you use more than one board, because it can compare them.

## Contributing

Issues and pull requests welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
