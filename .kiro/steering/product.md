# Product

boardsesh-mcp is an MCP server, not an application. The whole product is:

```
user adds MCP to their agent → sets BOARDSESH_USER → agent gets their multi-board logbook
```

- Users never run the binary directly; the MCP client launches `uvx boardsesh-mcp`.
- Users never call tools by name; they ask natural questions.
- **The default setup requires no secret.** Boardsesh serves logbook data publicly, so a display
  name is enough. Only require credentials for data that genuinely is viewer-only, and always name
  the variables to set in the error.
- Read-only, always. Do not add dashboards, login commands, keyring, token files or databases.
- The differentiator over kilter-mcp is multi-board: comparing boards, cross-board normalised
  grades, recommendations and the hold heatmap. Lean into that.
- Unofficial: built at the Boardsesh maintainer's suggestion, but not an official product. Never
  imply otherwise, and keep request volume low.
