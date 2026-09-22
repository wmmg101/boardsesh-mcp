# Security

- Default mode has no secret at all. Protect that property: prefer public queries.
- Never log or return passwords, tokens or `Authorization` headers. `redact()` any external text.
- Tokens in process memory only. No files, no keyring.
- The token request is split so the frame holding the password never raises (pytest and debuggers
  print the failing frame's locals). A test walks the traceback to prove it.
- After a rejected login, back off before retrying: Boardsesh rate-limits logins per IP with a
  bucket shared across clients behind their proxy.
- HTTP client logging is silenced because request URLs carry the user id.
- Tests use synthetic data only. Real-account tests are opt-in via `BOARDSESH_INTEGRATION=1`.
- Before any public push: `git diff`, grep for `Bearer `, `password=`, emails, real user ids.
- Never push to a remote unless asked.
