# pitch-mcp — Setup Guide

## What this server does

**pitch-mcp** listens to you sing and tells your AI assistant how well you are hitting the notes
in a piece of sheet music. You can either upload a recording to get a detailed accuracy report, or
sing live into your microphone and receive real-time feedback on your pitch and position in the
score. It is designed for choir singers who want to practise at home without needing a teacher or
accompanist.

---

## Requirements

- **Operating system:** Ubuntu, Debian, or Linux Mint 20.04 or later (64-bit)
- **Internet connection:** needed once to download the server the first time you use it
- **Microphone:** only needed for real-time mode — any built-in or USB mic works

---

## Installation

Open a terminal in the `pitch-mcp` folder and run:

```bash
bash install.sh
```

The script will:

1. Check that you are on a supported Linux distro
2. Check that **uv** (a fast Python tool runner) is installed — if not, it stops and asks you to [install it first](https://docs.astral.sh/uv/getting-started/installation/)
3. Ask whether you want real-time microphone support — if yes, it installs `libportaudio2`
   via `apt` (this requires your password)

That is all. No manual Python setup, no path editing.

> **Two modes explained**
>
> - **Offline analysis** — give the server a WAV recording and a sheet music file; it returns a
>   note-by-note accuracy report. This mode works with no extra system libraries.
> - **Real-time microphone monitoring** — the server listens via your mic while you sing and
>   reports your current position in the score plus whether you are sharp, flat, or on pitch.
>   This mode requires `libportaudio2`, which `install.sh` can install for you.
>
> You can always enable real-time mode later by running `sudo apt-get install libportaudio2`.

---

## Connect to your LLM client

After running `install.sh`, paste the snippet for your client into its config file, then
**restart the client**.

### Claude Desktop

Config file: `~/.config/claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "pitch": {
      "command": "uvx",
      "args": ["pitch-mcp"]
    }
  }
}
```

### Cursor

Config file: `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` in your workspace

```json
{
  "mcpServers": {
    "pitch": {
      "command": "uvx",
      "args": ["pitch-mcp"]
    }
  }
}
```

### Windsurf

Config file: `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "pitch": {
      "command": "uvx",
      "args": ["pitch-mcp"]
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
      "name": "pitch",
      "command": "uvx",
      "args": ["pitch-mcp"]
    }
  ]
}
```

### Zed

Config file: `~/.config/zed/settings.json`

```json
{
  "context_servers": {
    "pitch": {
      "command": {
        "path": "uvx",
        "args": ["pitch-mcp"]
      }
    }
  }
}
```

> **Tip:** If your client says it cannot find `uvx`, add the following to the snippet above
> alongside the `"args"` line:
> ```json
> "env": { "PATH": "/home/<your-username>/.local/bin:/usr/bin:/bin" }
> ```

---

## What you can ask your AI assistant

Once the server is connected, try prompts like these:

- *"Analyse this recording of me singing the alto part — how accurate was my pitch?"*
  (attach a WAV file and the sheet music)
- *"Load the soprano part from this MusicXML file and start monitoring my microphone."*
- *"Where am I in the score right now, and am I singing in tune?"*
- *"Give me a summary of how my practice session went — which notes did I struggle with?"*
- *"Stop listening and show me a report of my accuracy for each note in the piece."*

If you forget to stop, the microphone closes by itself after 10 minutes without activity. To change
that, add `"env": { "PITCH_SESSION_IDLE_MINUTES": "30" }` to the server's entry in your client
config (`"0"` turns it off).

---

## Something went wrong?

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common problems and fixes.
