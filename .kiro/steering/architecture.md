# Architecture

Layers (top depends on bottom, never the reverse):

```
server.py   → analytics.py, grades.py, models.py, client.py
analytics.py, grades.py → models.py only (pure, no I/O)
client.py   → auth.py, queries.py, endpoints.py, models.py, grades.py, config.py
auth.py     → endpoints.py, config.py
```

Rules
- `server.py` contains no HTTP or GraphQL; `client.py`/`auth.py` never import `mcp`.
- **Only the pinned documents in `queries.py` are ever sent.** The client accepts variables, never
  a caller-supplied document, so nothing can reach a mutation (`deleteTick`, `saveTick`, ...).
  New capability = new document, added deliberately.
- All URLs live in `endpoints.py`. HTTP is `httpx2` with an injectable `AsyncClient` for tests.
- MCP SDK is `mcp>=2`: `from mcp.server import MCPServer`, tools use
  `annotations=ToolAnnotations(read_only_hint=True)`, errors use the SDK's `ToolError`.
- Every tool argument needs an `Annotated[..., Field(description=...)]`; a test enforces it.
- Data semantics: `status` (`flash`/`send`/`attempt`) is authoritative, never inferred from try
  counts; identity for grouping is `(board, climb_uuid, angle)`; entries are never deduplicated;
  personal grade beats consensus and the ascents feed has no `effectiveDifficulty`, so
  `models.py` coalesces it.
- `boardsesh_grade` is suppressed unless its confidence tier is ascent-backed (not `setter_only`
  and not any `*_estimate`).
- Anything turning a timestamp into a day or period takes `tz: tzinfo`; use `Ascent.local_date(tz)`.
- Keep the User-Agent boring: Boardsesh's WAF blocks agentic crawler UAs zone-wide.
