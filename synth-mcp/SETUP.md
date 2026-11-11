# synth-mcp — Setup Guide

**synth-mcp** turns sheet music into audio so you can hear any voice part on its own.
Give it a MusicXML file, choose which parts to include (Soprano, Alto, Tenor, Bass, or any combination), and your AI assistant produces a WAV audio file you can play back right away.
It also lets you slow down or speed up the tempo — useful when you're learning a new piece.

---

## Requirements

- **Operating system:** Ubuntu, Debian, or Linux Mint 20.04 or later
- **Internet access:** needed during installation to download a soundfont (a small audio file, ~6 MB)
- No other software needs to be installed beforehand — `install.sh` handles everything

---

## Installation

Open a terminal in the folder where you downloaded this repository and run:

```bash
bash synth-mcp/install.sh
```

The script will:
1. Check that `uv` (the tool that runs synth-mcp) is installed — if not, it stops and asks you to [install it first](https://docs.astral.sh/uv/getting-started/installation/)
2. Install the audio library synth-mcp needs (`libfluidsynth-dev`)
3. Find or download a soundfont — the audio "instrument bank" used to produce sound
4. Print a ready-to-paste config snippet for your LLM client

At the end you will see a block of text labelled with your LLM client name. Copy that block — you'll need it in the next step.

---

## What is a soundfont?

A soundfont is a file that tells the synthesiser what each instrument sounds like.
Think of it as a collection of recorded piano, strings, and choir samples packaged into one file.
`install.sh` downloads **TimGM6mb.sf2** (~6 MB) automatically and stores it in `~/.local/share/sounds/sf2/`.

If you want higher-quality audio or a different set of sounds, see [docs/soundfonts.md](docs/soundfonts.md).

---

## Connect to your LLM client

After running `install.sh`, paste the config snippet it printed into the correct file for your client, then restart the client.

> **Note:** Replace `~/.local/share/sounds/sf2/TimGM6mb.sf2` in the snippets below with the soundfont path that `install.sh` printed for you, if it differs.

---

### Claude Desktop

Config file: `~/.config/claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "synth": {
      "command": "uvx",
      "args": ["synth-mcp"],
      "env": {
        "SYNTH_SOUNDFONT_PATH": "~/.local/share/sounds/sf2/TimGM6mb.sf2"
      }
    }
  }
}
```

If the file already has other servers listed, add the `"synth": { ... }` block inside the existing `"mcpServers"` object.

---

### Cursor

Config file: `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` inside your project folder

```json
{
  "mcpServers": {
    "synth": {
      "command": "uvx",
      "args": ["synth-mcp"],
      "env": {
        "SYNTH_SOUNDFONT_PATH": "~/.local/share/sounds/sf2/TimGM6mb.sf2"
      }
    }
  }
}
```

---

### Windsurf

Config file: `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "synth": {
      "command": "uvx",
      "args": ["synth-mcp"],
      "env": {
        "SYNTH_SOUNDFONT_PATH": "~/.local/share/sounds/sf2/TimGM6mb.sf2"
      }
    }
  }
}
```

---

### VS Code + Continue

Config file: `~/.continue/config.json`

Add the following inside the `"mcpServers"` array (create the array if it doesn't exist):

```json
{
  "mcpServers": [
    {
      "name": "synth",
      "command": "uvx",
      "args": ["synth-mcp"],
      "env": {
        "SYNTH_SOUNDFONT_PATH": "~/.local/share/sounds/sf2/TimGM6mb.sf2"
      }
    }
  ]
}
```

---

### Zed

Config file: `~/.config/zed/settings.json`

Add the following inside the top-level object:

```json
{
  "context_servers": {
    "synth": {
      "command": {
        "path": "uvx",
        "args": ["synth-mcp"],
        "env": {
          "SYNTH_SOUNDFONT_PATH": "~/.local/share/sounds/sf2/TimGM6mb.sf2"
        }
      }
    }
  }
}
```

---

## What you can ask your AI assistant

Once the server is connected, try these prompts:

- *"What voice parts are in this MusicXML file?"* — lists every part and how many measures it has
- *"Play back just the soprano and alto parts from this score so I can practise with them."* — produces a WAV file with only those two parts
- *"Generate a practice track of the tenor line at 70% speed — I'm still learning the notes."* — slows the tempo so you can follow along more easily
- *"Create an audio file with all parts except bass so the bass section can hear what everyone else is singing."*
- *"Render the full SATB choir from this MusicXML file at normal speed."*

---

## Something went wrong?

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for fixes for the most common problems,
including what to do if no audio is produced, if the server doesn't appear in your client,
or if `uvx` is not found.
