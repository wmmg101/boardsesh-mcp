# Development conventions

- `uv` for everything: `uv sync`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`.
- Python ≥ 3.10, `from __future__ import annotations`, dataclasses for our own models.
- Line length 100; ruff config in `pyproject.toml`.
- pytest + pytest-asyncio (`asyncio_mode = "auto"`); mock HTTP with `httpx2.MockTransport`; test
  tools in-process with `mcp.Client(server)`.
- Every new tool: docstring saying when to use it, described arguments, read-only annotation,
  structured return, and a test.
- Validate new GraphQL documents against the live API before relying on them; the schema in
  boardsesh/boardsesh is the source of truth and drifts from their published docs.
- Keep `.kiro/specs/boardsesh-mcp/` and this steering in sync with behaviour.
- main is protected: branch → PR → CI (`ci` check) → squash-merge. Only commit when asked.
