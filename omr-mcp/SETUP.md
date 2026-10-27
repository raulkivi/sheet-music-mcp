# omr-mcp — Setup Guide

**omr-mcp** reads a photo or scan of a music score and converts it into a digital format your AI assistant can work with. Point it at a PNG or JPEG of sheet music and it returns MusicXML — a standard file format that music software understands. This is the starting point of the choir music assistant pipeline.

---

## Requirements

- **Operating system:** Ubuntu, Debian, or Linux Mint 20.04 or later
- **System libraries:** None — omr-mcp is fully self-contained

---

## Installation

Open a terminal in the `omr-mcp` folder and run:

```bash
bash install.sh
```

The script will:
1. Check that your system is apt-based (Ubuntu / Debian / Mint)
2. Check that `uv` is installed — if not, it stops and asks you to [install it first](https://docs.astral.sh/uv/getting-started/installation/)
3. Set up the Python environment

That's it. No other steps are needed before connecting your AI client.

---

> **First-run notice**
>
> The first time you ask omr-mcp to process a score, it automatically downloads
> approximately **100 MB of AI model files**. This takes **about 5 minutes**
> depending on your internet connection. The server will appear unresponsive
> during this time — this is normal. The download happens only once; all future
> runs use the cached files.

---

## Connect to your AI assistant

After installation, tell your AI client how to start omr-mcp by adding the
following config snippet to the appropriate file. You do not need to edit any
file paths — `uvx` handles everything automatically.

### Claude Desktop

Config file: `~/.config/claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "omr": {
      "command": "uvx",
      "args": ["omr-mcp"]
    }
  }
}
```

### Cursor

Config file: `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "omr": {
      "command": "uvx",
      "args": ["omr-mcp"]
    }
  }
}
```

### Windsurf

Config file: `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "omr": {
      "command": "uvx",
      "args": ["omr-mcp"]
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
      "name": "omr",
      "command": "uvx",
      "args": ["omr-mcp"]
    }
  ]
}
```

### Zed

Config file: `~/.config/zed/settings.json`

```json
{
  "context_servers": {
    "omr": {
      "command": {
        "path": "uvx",
        "args": ["omr-mcp"]
      }
    }
  }
}
```

After adding the snippet, **restart your AI client** so it picks up the change.

---

## What you can ask your AI assistant

Once connected, you can ask things like:

- *"Convert this score image to MusicXML: /home/alice/scores/soprano.png"*
- *"Read the sheet music in this file and tell me how many measures it has."*
- *"I have a scan of a choir piece — can you turn it into a format MuseScore can open?"*
- *"Digitize pages 1 and 2 of my score (soprano_p1.png and soprano_p2.png) and merge them."*
- *"What sheet music formats does this server support?"*

---

## Something went wrong?

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for solutions to common problems.
