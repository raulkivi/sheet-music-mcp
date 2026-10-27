# sheet-music-mcp-core

Shared helpers for the [sheet-music MCP servers](https://github.com/raulkivi/sheet-music-mcp): error responses, voice-part selection, deprecated parameter names, tool annotations, result content, MCP handler wiring and score references (scores passed as confined file paths, safe MusicXML and `.mxl` reading, and the shared `describe_score` tool).

This is a library, not an MCP server. Install one of the servers instead (for example `uvx render-mcp`); they depend on this package.

See [docs/conventions.md](https://github.com/raulkivi/sheet-music-mcp/blob/main/docs/conventions.md#shared-core-library) for the rules each module implements.
