# Security

boardsesh-mcp reads one person's climbing logbook. In the default setup it holds no secret at
all, which is the main thing that makes it safe.

## What it does with your data

- **Default mode holds no secret.** `BOARDSESH_USER` is your public display name. Everything the
  server reads in this mode is what your Boardsesh profile already shows publicly.
- **Optional credentials.** If you set `BOARDSESH_EMAIL` and `BOARDSESH_PASSWORD`, they are sent
  once to Boardsesh's own login endpoint in exchange for an access token and a refresh token.
  Tokens live in process memory for the life of the MCP process and are never written to disk, a
  keychain or a cache. The password is never stored.
- The server talks to two hosts only: `ws.boardsesh.com` (API and login) and `www.boardsesh.com`
  (the hold-heatmap route). No telemetry, no third-party endpoint.
- Every tool is read-only. The GraphQL layer can send **only** the fixed documents in
  `src/boardsesh_mcp/queries.py`, with variables; it never accepts a document from a caller. That
  is what makes it impossible for a tool, or a prompt injected into one, to reach a mutation such
  as `deleteTick`.
- Credentials, tokens and `Authorization` headers never appear in tool output, log lines or error
  messages. Error text passes through a redaction step, and the token request is structured so a
  Python traceback's failing frame does not hold the password (tests enforce both).
- HTTP client logging is silenced, because request URLs carry your user id.
- After a rejected login the server waits before retrying, so a mistyped password cannot turn into
  a burst of failed logins against Boardsesh's shared per-IP rate limit.

## What it cannot protect you from

- Your MCP client's configuration file. If you put a password directly in it rather than using an
  environment-variable placeholder, anyone who can read that file can read the password. Keep such
  files out of version control; see [docs/clients.md](docs/clients.md).
- The process environment. MCP clients pass configuration to local servers as environment
  variables, which other processes running as the same OS user can read. This is how every stdio
  MCP server receives configuration.
- The AI model you are talking to. Tool output (your climbs, grades, dates) goes to whatever model
  your client uses. Credentials do not, but your climbing history does.
- Full-account access. Boardsesh has no scoped or read-only tokens, so a token obtained with your
  password could in principle do anything your account can. This server only ever issues reads,
  and the code that talks to Boardsesh is small enough to audit (`client.py`, `auth.py`,
  `queries.py`, `endpoints.py`).

## Supported versions

Only the latest release on PyPI receives fixes. Upgrade with `uvx --refresh boardsesh-mcp`.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private reporting:

**https://github.com/wmmg101/boardsesh-mcp/security/advisories/new**

Include what you found, how to reproduce it, and the version (`boardsesh-mcp --version`). You
should get an acknowledgement within a few days; once fixed, the advisory is published with credit
to you unless you prefer otherwise.

Bugs that are not security problems (a wrong number, an outdated client snippet) belong in the
normal issue tracker. Problems with Boardsesh itself belong upstream at
<https://github.com/boardsesh/boardsesh>.
