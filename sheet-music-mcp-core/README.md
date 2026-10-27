# sheet-music-mcp-core

Shared helpers for the [sheet-music MCP servers](https://github.com/raulkivi/sheet-music-mcp): error responses, voice-part selection, deprecated parameter names, tool annotations, result content (file links, inline PNG images and short WAV clips), MCP handler wiring, score references (scores passed as confined file paths, safe MusicXML and `.mxl` reading, and the shared `describe_score` tool), measure ranges (`measures: [start, end]` in printed bar numbers, cutting a score down to those bars with the key, time, clef and tempo in force) and each part's first note.

This is a library, not an MCP server. Install one of the servers instead (for example `uvx render-mcp`); they depend on this package.

See [docs/conventions.md](https://github.com/raulkivi/sheet-music-mcp/blob/main/docs/conventions.md#shared-core-library) for the rules each module implements.
