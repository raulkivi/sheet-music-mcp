# comparer-mcp — Setup Guide

## What this server does

This server lets your AI assistant compare two music scores (in MusicXML format) and tell you
exactly what's different — which parts are missing, which measures don't line up, and which
individual notes changed pitch or duration. Useful for checking a digitized score against the
original, comparing two arrangements of the same piece, or verifying that an edit only changed
what you intended.

---

## Requirements

- **Operating system:** Ubuntu, Debian, or Linux Mint 20.04 or newer
- **System libraries:** None — this is one of the simplest servers in the suite to install

---

## Installation

Open a terminal in the `comparer-mcp` folder and run:

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
    "comparer": {
      "command": "uvx",
      "args": ["comparer-mcp"]
    }
  }
}
```

### Cursor

Config file: `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "comparer": {
      "command": "uvx",
      "args": ["comparer-mcp"]
    }
  }
}
```

### Windsurf

Config file: `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "comparer": {
      "command": "uvx",
      "args": ["comparer-mcp"]
    }
  }
}
```

### VS Code + Continue

Config file: `~/.continue/config.json`

Add the following inside the `"mcpServers"` array (create the array if it does not exist):

```json
{
  "name": "comparer",
  "command": "uvx",
  "args": ["comparer-mcp"]
}
```

### Zed

Config file: `~/.config/zed/settings.json`

Add the following inside the `"context_servers"` object:

```json
"comparer": {
  "command": {
    "path": "uvx",
    "args": ["comparer-mcp"]
  }
}
```

---

## What you can ask your AI assistant

Once the server is connected, try prompts like these:

- *"Compare this reference score against the OMR output and tell me what's wrong."*
- *"How similar are these two arrangements, overall?"*
- *"What changed in the Alto part between measures 17 and 24?"*
- *"Did my edit only change the tenor line, or did something else shift too?"*
- *"Run a health check on the comparer server."*

---

## Something went wrong?

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for help with common problems.
