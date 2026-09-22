# Using boardsesh-mcp with other MCP clients

boardsesh-mcp is a standard local MCP server (stdio transport), so any MCP client that can launch
a local command can use it. Every setup below is the same three facts:

```text
command:  uvx
args:     boardsesh-mcp
env:      BOARDSESH_USER   (your Boardsesh display name — not a secret)
```

Prerequisite everywhere: [`uv`](https://docs.astral.sh/uv/) installed (`uvx` ships with it).

**There is nothing sensitive in the basic setup**, so you can paste the display name straight into
the config file. Credentials are optional; see [below](#optional-unlocking-the-credential-tools).

For Kiro, see the [README](../README.md#add-to-your-agent).

## Setting the environment variables

The placeholder syntax inside a client's config (`${VAR}`, `${env:VAR}`, ...) is the same on every
OS, but making a variable visible to the client differs. This only matters if you use the optional
credentials; the display name can be a literal.

**macOS / Linux (zsh, bash)** — add to `~/.zshrc` or `~/.bashrc`, then open a new terminal:

```bash
export BOARDSESH_EMAIL="you@example.com"
export BOARDSESH_PASSWORD="your-boardsesh-password"
```

Terminal clients (Claude Code, Codex CLI, Gemini CLI, Kiro CLI) see these directly. GUI apps
started from the Dock, Finder or a desktop launcher do **not** read shell rc files. Either launch
the app from a terminal (`open -a Cursor`, `code .`, `zed .`), or set them for the login session:

```bash
# macOS, per login session
launchctl setenv BOARDSESH_PASSWORD "your-boardsesh-password"
```

On Linux desktops, `~/.profile` is read at login and applies to GUI apps.

**Windows (PowerShell)** — persistent for your user; restart the client afterwards:

```powershell
[Environment]::SetEnvironmentVariable("BOARDSESH_PASSWORD", "your-boardsesh-password", "User")
```

(`$env:BOARDSESH_PASSWORD = "..."` lasts only for the current window; `setx` is the cmd.exe
equivalent.)

---

## Claude Desktop

Config file (Claude menu → Settings → Developer → Edit Config):

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "boardsesh": {
      "command": "uvx",
      "args": ["boardsesh-mcp"],
      "env": {
        "BOARDSESH_USER": "Your Boardsesh Display Name"
      }
    }
  }
}
```

Claude Desktop does not document environment-variable placeholders, so use literal values.
Restart the app fully after editing.
Docs: <https://modelcontextprotocol.io/docs/develop/connect-local-servers>

## Claude Code (CLI)

```bash
claude mcp add --transport stdio --scope user \
  --env BOARDSESH_USER="Your Boardsesh Display Name" \
  boardsesh -- uvx boardsesh-mcp
```

Or in `.mcp.json` (project) / `~/.claude.json` (user). Claude Code expands `${VAR}`:

```json
{
  "mcpServers": {
    "boardsesh": {
      "type": "stdio",
      "command": "uvx",
      "args": ["boardsesh-mcp"],
      "env": { "BOARDSESH_USER": "Your Boardsesh Display Name" }
    }
  }
}
```

Docs: <https://code.claude.com/docs/en/mcp>

## OpenAI Codex (CLI, IDE extension, ChatGPT desktop → Codex)

```bash
codex mcp add boardsesh --env BOARDSESH_USER="Your Boardsesh Display Name" -- uvx boardsesh-mcp
```

Or in `~/.codex/config.toml`. `env_vars` forwards variables from your shell; `env` sets literals:

```toml
[mcp_servers.boardsesh]
command = "uvx"
args = ["boardsesh-mcp"]
env = { BOARDSESH_USER = "Your Boardsesh Display Name" }
# to forward optional credentials from your shell instead of writing them here:
# env_vars = ["BOARDSESH_EMAIL", "BOARDSESH_PASSWORD"]
```

Docs: <https://developers.openai.com/codex/mcp/>

## ChatGPT (chat interface)

Not supported directly. ChatGPT's chat surface only connects to **remote** MCP servers over HTTP
via Developer-mode connectors; it cannot launch a local command. The Codex side of the ChatGPT
desktop app does support local servers — use the section above.
Docs: <https://developers.openai.com/api/docs/guides/developer-mode/>

## Cursor

[![Install in Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](cursor://anysphere.cursor-deeplink/mcp/install?name=boardsesh&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJib2FyZHNlc2gtbWNwIl0sImVudiI6eyJCT0FSRFNFU0hfVVNFUiI6IllvdXIgQm9hcmRzZXNoIERpc3BsYXkgTmFtZSJ9fQ==)

(Edit the display name after installing.) Or edit `~/.cursor/mcp.json` (global) or
`.cursor/mcp.json` (project). Cursor's placeholder syntax is `${env:NAME}`:

```json
{
  "mcpServers": {
    "boardsesh": {
      "command": "uvx",
      "args": ["boardsesh-mcp"],
      "env": {
        "BOARDSESH_USER": "Your Boardsesh Display Name",
        "BOARDSESH_EMAIL": "${env:BOARDSESH_EMAIL}",
        "BOARDSESH_PASSWORD": "${env:BOARDSESH_PASSWORD}"
      }
    }
  }
}
```

Docs: <https://cursor.com/docs/mcp>

## VS Code (GitHub Copilot)

[Install in VS Code](vscode:mcp/install?%7B%22name%22%3A%22boardsesh%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22boardsesh-mcp%22%5D%2C%22env%22%3A%7B%22BOARDSESH_USER%22%3A%22%24%7Binput%3Aboardsesh-user%7D%22%7D%2C%22inputs%22%3A%5B%7B%22type%22%3A%22promptString%22%2C%22id%22%3A%22boardsesh-user%22%2C%22description%22%3A%22Your%20Boardsesh%20display%20name%22%7D%5D%7D)

VS Code uses a `servers` key and can prompt once for values via `inputs`, storing secrets
securely. Put this in `.vscode/mcp.json` or your user `mcp.json` (command palette → **MCP: Open
User Configuration**):

```json
{
  "inputs": [
    { "type": "promptString", "id": "boardsesh-user", "description": "Boardsesh display name" },
    { "type": "promptString", "id": "boardsesh-password", "description": "Boardsesh password (optional)", "password": true }
  ],
  "servers": {
    "boardsesh": {
      "type": "stdio",
      "command": "uvx",
      "args": ["boardsesh-mcp"],
      "env": {
        "BOARDSESH_USER": "${input:boardsesh-user}"
      }
    }
  }
}
```

Docs: <https://code.visualstudio.com/docs/copilot/customization/mcp-servers>

## Windsurf

Edit `~/.codeium/windsurf/mcp_config.json` (Settings → Cascade → MCP Servers → raw config).
Placeholder syntax is `${env:NAME}`:

```json
{
  "mcpServers": {
    "boardsesh": {
      "command": "uvx",
      "args": ["boardsesh-mcp"],
      "env": { "BOARDSESH_USER": "Your Boardsesh Display Name" }
    }
  }
}
```

Docs: <https://docs.windsurf.com/windsurf/cascade/mcp>

## Gemini CLI

```bash
gemini mcp add -s user -e BOARDSESH_USER="Your Boardsesh Display Name" boardsesh uvx boardsesh-mcp
```

Or in `~/.gemini/settings.json`. Gemini CLI expands `$VAR` / `${VAR}`. Note it strips inherited
variables whose names contain `PASSWORD` unless they are listed explicitly in `env`, so if you use
the optional credentials, keep both entries:

```json
{
  "mcpServers": {
    "boardsesh": {
      "command": "uvx",
      "args": ["boardsesh-mcp"],
      "env": {
        "BOARDSESH_USER": "Your Boardsesh Display Name",
        "BOARDSESH_EMAIL": "${BOARDSESH_EMAIL}",
        "BOARDSESH_PASSWORD": "${BOARDSESH_PASSWORD}"
      }
    }
  }
}
```

Docs: <https://geminicli.com/docs/tools/mcp-server/>

## Zed

Settings → AI → MCP Servers → Add Local Server, or in `settings.json`
(`~/.config/zed/settings.json` on macOS/Linux, `%APPDATA%\Zed\settings.json` on Windows):

```json
{
  "context_servers": {
    "boardsesh": {
      "command": "uvx",
      "args": ["boardsesh-mcp"],
      "env": { "BOARDSESH_USER": "Your Boardsesh Display Name" }
    }
  }
}
```

Zed does not document environment-variable placeholders, so use literal values.
Docs: <https://zed.dev/docs/ai/mcp>

## Kiro CLI

Same files and format as the Kiro IDE (`~/.kiro/settings/mcp.json`), or:

```bash
kiro-cli mcp add --name boardsesh --scope global --command uvx --args boardsesh-mcp \
  --env BOARDSESH_USER="Your Boardsesh Display Name"
```

Docs: <https://kiro.dev/docs/mcp/configuration/>

---

## Optional: unlocking the credential tools

Eight of the twelve tools work with `BOARDSESH_USER` alone. These four also need
`BOARDSESH_EMAIL` and `BOARDSESH_PASSWORD`, because they need your saved board configuration
(layout, size, hold sets), which Boardsesh only reveals to the logged-in owner:

- `boardsesh_recommend_climbs`
- `boardsesh_search_climbs`
- `boardsesh_find_similar_climbs`
- `boardsesh_get_hold_heatmap`

Your password is exchanged once for a token that lives in memory only, and is never written to
disk. Prefer an environment-variable placeholder over a literal in a config file, and keep any
config file containing one out of version control.

## Something else?

If your client is not listed but supports local stdio MCP servers, use `command: uvx`,
`args: ["boardsesh-mcp"]` and the `BOARDSESH_USER` environment variable. Pull requests adding
verified instructions for other clients are welcome.
