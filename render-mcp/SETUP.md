# render-mcp — Setup Guide

## What this server does

**render-mcp** turns sheet music files (MusicXML format) into PDF documents you can print or PNG images you can view on screen. You ask your AI assistant to render a score, and it hands back a ready-to-use file — no music software required.

---

## Requirements

- **Operating system:** Ubuntu, Debian, or Linux Mint 20.04 or newer
- **System library:** `libcairo2` — the installation script installs this for you automatically

---

## Installation

Open a terminal in the `render-mcp` folder and run:

```bash
bash install.sh
```

The script will:
1. Check that you are on a supported Linux system
2. Check that `uv` (a fast Python tool runner) is installed — if not, it stops and asks you to [install it first](https://docs.astral.sh/uv/getting-started/installation/)
3. Install the `libcairo2` system library

That's it. No further setup is needed — your AI client will download and run the server automatically the first time you use it.

---

## Connect to your LLM client

After installation, add the server to your AI client's config file. Find your client below, open the config file in a text editor, and paste the snippet inside the `"mcpServers"` block (create the file if it does not exist yet). Then restart your client.

### Claude Desktop

Config file: `~/.config/claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "render": {
      "command": "uvx",
      "args": ["render-mcp"]
    }
  }
}
```

### Cursor

Config file: `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "render": {
      "command": "uvx",
      "args": ["render-mcp"]
    }
  }
}
```

### Windsurf

Config file: `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "render": {
      "command": "uvx",
      "args": ["render-mcp"]
    }
  }
}
```

### VS Code + Continue

Config file: `~/.continue/config.json`

```json
{
  "mcpServers": [
    {
      "name": "render",
      "command": "uvx",
      "args": ["render-mcp"]
    }
  ]
}
```

### Zed

Config file: `~/.config/zed/settings.json`

```json
{
  "context_servers": {
    "render": {
      "command": {
        "path": "uvx",
        "args": ["render-mcp"]
      }
    }
  }
}
```

> **Tip:** If your client says it cannot find `uvx` after restarting, add `"env": { "PATH": "/home/<your-username>/.local/bin:/usr/bin:/bin" }` to the server entry.

---

## What you can ask your AI assistant

Once the server is connected, try prompts like these:

- *"Render `~/scores/soprano_part.xml` as a PDF and save it to my Desktop."*
- *"Convert this MusicXML file to a PNG image at 150 DPI so I can share it."*
- *"Create a printable PDF of `alto_voice.xml` with all pages included."*
- *"Turn `choir_full_score.xml` into a PNG of just the first page."*
- *"Render `bass_part.xml` to a high-resolution PNG for the choir's website."*

---

## Something went wrong?

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common problems and fixes.
