# Contributing to boardsesh-mcp

Issues and pull requests are welcome.

## Development setup

```bash
git clone https://github.com/wmmg101/boardsesh-mcp.git
cd boardsesh-mcp
uv sync
uv run pytest
uv run ruff check .
uv run ruff format .
```

Python ≥ 3.10. No Boardsesh account is needed for the test suite.

## Architecture

```
agent
  │  MCP (stdio)
  ▼
server.py      MCP tools: parse args, call the client, run analytics, return dicts
  │
  ▼
analytics.py   pure functions over list[Ascent]  (no I/O)
grades.py      difficulty id → label, plus the confidence gate on Boardsesh grades
  │
  ▼
models.py      Ascent, Grade, HoldStat, BoardTickCount; tolerant parsing
  │
  ▼
client.py      BoardseshClient: sends only the pinned documents; heatmap REST call
queries.py     every GraphQL document this client can send
auth.py        TokenManager: optional email+password → in-memory JWT + refresh
config.py      Settings from BOARDSESH_*; redact() helper
endpoints.py   every URL in one place
```

Rules that keep this maintainable:

- `server.py` never does HTTP or GraphQL; `client.py`/`auth.py` never import `mcp`.
- `analytics.py` and `grades.py` do no I/O, so they are tested with plain data.
- **Only the pinned documents in `queries.py` are ever sent.** The client takes variables, never
  a caller-supplied document, so no tool and no prompt injected into one can reach a mutation
  such as `deleteTick`. Adding a capability means adding a document there deliberately.
- Only `config.py`, `auth.py` and `client.py` ever see the password or tokens.
- HTTP goes through `httpx2` (already a dependency of `mcp`); the `AsyncClient` is injectable so
  tests use `httpx2.MockTransport`.
- Keep the User-Agent boring. Boardsesh's WAF blocks agentic crawler user agents (`gptbot`,
  `claudebot`, `perplexitybot`, …) across the whole zone; a test asserts ours is clean.

## Data semantics

These drive every statistic. They come from Boardsesh's own `docs/ascents-and-attempts.md`:

- One entry is one climb at one angle on one board at one time, with a try count. Entries are
  never deduplicated.
- `status` is the source of truth: `flash` / `send` / `attempt`. Never infer it from try counts.
- A climb's identity for grouping is `(board, climb_uuid, angle)`.
- The user's personal grade wins over the consensus; the ascents feed has no `effectiveDifficulty`
  field, so `models.py` coalesces it the way Boardsesh does.
- `boardsesh_grade` is only reported when its confidence tier is ascent-backed. `setter_only` and
  the three `*_estimate` tiers describe angles nobody has climbed and are suppressed.

## Two tiers of access

Most Boardsesh read queries are public and take a `userId`, so the default configuration needs no
secret. Keep it that way: a new tool should only require credentials if the data genuinely is
viewer-only, and when it does, the error must name the variables to set. `tests/test_server.py`
asserts that for every credential-gated tool.

## Adding a tool

1. Add the GraphQL document to `queries.py` if the data is not already fetched.
2. Add a client method that parses into a model.
3. Add a pure function in `analytics.py` if there is any aggregation, and unit-test it.
4. Register the tool in `server.py` with `@_read_only_tool(server, "boardsesh_...")`. The
   docstring is what the agent reads: say *when* to use it. Every argument needs a `Field`
   description (a test enforces this).
5. Add an end-to-end test in `tests/test_server.py` using `mcp.Client(server)` and the
   `FakeBoardsesh` backend in `tests/conftest.py`.
6. Add the tool to the README table.

## Mocking Boardsesh

`tests/conftest.py` has `FakeBoardsesh`, an `httpx2.MockTransport` handler that answers the
GraphQL endpoint (dispatching on operation name), the login endpoints and the heatmap route. Flip
its flags (`password_ok`, `refresh_ok`, `login_status`, `graphql_status`, `rate_limit_queue`) to
script failure modes. Keep fixtures synthetic.

### Optional real-account check

`tests/integration/` runs only when `BOARDSESH_INTEGRATION=1` and `BOARDSESH_USER` are set. It
asserts shapes and never prints entries. Skipped in CI.

## Security requirements for every change

- Never log or return passwords, tokens or `Authorization` headers.
- Wrap text from exceptions and responses with `config.redact()` before surfacing it.
- No real user ids, emails or API dumps in fixtures, tests or docs.
- Before pushing: `git diff`, then grep for `Bearer `, `password=` and `@`-emails.

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml` and `src/boardsesh_mcp/__init__.py`, add a `CHANGELOG.md`
   entry, and update both version fields in `server.json`.
2. Open a PR, let CI pass, squash-merge.
3. `git tag -a vX.Y.Z -m "boardsesh-mcp X.Y.Z" && git push origin refs/tags/vX.Y.Z`.
4. Approve the `pypi` environment on the Actions run; it publishes via Trusted Publishing.
5. `gh release create vX.Y.Z --notes-file <changelog section>`.
6. Publish to the MCP registry: `mcp-publisher login github && mcp-publisher publish server.json`.
