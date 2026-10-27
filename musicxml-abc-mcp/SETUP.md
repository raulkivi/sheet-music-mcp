# musicxml-abc-mcp — Setup Guide

## What this server does

This server lets your AI assistant read and edit music scores by converting them between two
formats: MusicXML (the standard format used by notation software like MuseScore and Sibelius) and
ABC notation (a compact text format that the AI can understand and modify directly). You can hand
the AI a score, ask it to transpose a part or fix a rhythm, and get back a corrected file — all
in plain conversation.

---

## Requirements

- **Operating system:** Ubuntu, Debian, or Linux Mint 20.04 or newer
- **System libraries:** None — this is the simplest server in the suite to install

---

## Installation

Open a terminal in the `musicxml-abc-mcp` folder and run:

```bash
bash install.sh
```

The script will:
1. Check that your system is Ubuntu, Debian, or Linux Mint
2. Check that `uv` (a fast Python tool runner) is installed — if not, it stops and asks you to [install it first](https://docs.astral.sh/uv/getting-started/installation/)
3. Confirm that no additional system libraries are needed
4. Print ready-to-paste config snippets for each supported LLM client

---

## Connect to your LLM client

After installation, add the server to your LLM client by pasting one of the snippets below into
the correct config file. Then **restart the client** so it picks up the change.

### Claude Desktop

Config file: `~/.config/claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "musicxml-abc": {
      "command": "uvx",
      "args": ["musicxml-abc-mcp"]
    }
  }
}
```

### Cursor

Config file: `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "musicxml-abc": {
      "command": "uvx",
      "args": ["musicxml-abc-mcp"]
    }
  }
}
```

### Windsurf

Config file: `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "musicxml-abc": {
      "command": "uvx",
      "args": ["musicxml-abc-mcp"]
    }
  }
}
```

### VS Code + Continue

Config file: `~/.continue/config.json`

Add the following inside the `"mcpServers"` array (create the array if it does not exist):

```json
{
  "name": "musicxml-abc",
  "command": "uvx",
  "args": ["musicxml-abc-mcp"]
}
```

### Zed

Config file: `~/.config/zed/settings.json`

Add the following inside the `"context_servers"` object:

```json
"musicxml-abc": {
  "command": {
    "path": "uvx",
    "args": ["musicxml-abc-mcp"]
  }
}
```

---

## What you can ask your AI assistant

Once the server is connected, try prompts like these:

- *"Convert this MusicXML file to ABC notation so you can read it."*
- *"Here is a score in ABC notation — convert it back to MusicXML so I can open it in MuseScore."*
- *"Extract just the soprano part from this MusicXML file and give it to me as ABC notation."*
- *"Check whether this ABC notation is valid and tell me about any errors."*
- *"Transpose the melody in this ABC score up by a whole step, then convert it back to MusicXML."*

---

## Something went wrong?

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for help with common problems.
