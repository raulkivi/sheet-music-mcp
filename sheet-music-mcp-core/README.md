# sheet-music-mcp-core

Shared helpers for the [sheet-music MCP servers](https://github.com/raulkivi/sheet-music-mcp): error responses, voice-part selection, deprecated parameter names, tool annotations, result content (file links, inline PNG images and short WAV clips), MCP handler wiring, score references (scores passed as confined file paths, safe MusicXML and `.mxl` reading, and the shared `describe_score` tool), measure ranges (`measures: [start, end]` in printed bar numbers, cutting a score down to those bars with the key, time, clef and tempo in force), each part's first note, MCP Apps UI resources (`ui://` HTML apps that tools link to, served from the server package), and opaque artifact ids that let an app read a large output file, such as a practice WAV, in 1 MiB chunks without ever passing a path.

This is a library, not an MCP server. Install one of the servers instead (for example `uvx render-mcp`); they depend on this package.

See [docs/conventions.md](https://github.com/raulkivi/sheet-music-mcp/blob/main/docs/conventions.md#shared-core-library) for the rules each module implements.
