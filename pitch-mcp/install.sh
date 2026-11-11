#!/usr/bin/env bash
# pitch-mcp/install.sh — set up pitch-mcp on Ubuntu / Debian / Linux Mint
# After running this script, paste the config snippet below into your LLM client.

set -euo pipefail

# ── 1. Check for apt-based distro ─────────────────────────────────────────────
if ! command -v apt-get &>/dev/null && [ ! -f /etc/debian_version ]; then
    echo "ERROR: This script requires an apt-based Linux distro (Ubuntu, Debian, or Linux Mint)."
    echo "       macOS, Windows, and non-apt Linux distros are not supported."
    exit 1
fi

echo "✓ apt-based distro detected"

# ── 2. Require uv ──────────────────────────────────────
if command -v uv &>/dev/null; then
    echo "✓ uv already installed: $(uv --version)"
else
    echo "ERROR: uv is not installed. Install it, then re-run this script:"
    echo "       https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

# ── 3. Install libportaudio2 (optional — real-time mic mode only) ──────────────
echo ""
echo "pitch-mcp has two modes:"
echo "  • Offline analysis  — analyse a pre-recorded WAV file (no extra system libs needed)"
echo "  • Real-time mic     — listen via microphone while you sing (requires libportaudio2)"
echo ""
read -r -p "Install libportaudio2 for real-time mic support? [Y/n] " _answer
_answer="${_answer:-Y}"
if [[ "$_answer" =~ ^[Yy]$ ]]; then
    echo "→ Installing libportaudio2 (requires sudo)..."
    sudo apt-get update -qq
    sudo apt-get install -y libportaudio2
    echo "✓ libportaudio2 installed — both offline and real-time modes are available"
else
    echo "  Skipping libportaudio2. Offline analysis (analyze_recording) will work fine."
    echo "  To enable real-time mic later, run: sudo apt-get install libportaudio2"
fi

# ── 4. Set up the server venv ─────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "→ Running uv sync in $SCRIPT_DIR..."
cd "$SCRIPT_DIR"
uv sync
echo "✓ pitch-mcp venv ready"

# ── 5. Print config snippets ──────────────────────────────────────────────────
cat <<'EOF'

═══════════════════════════════════════════════════════════════════════════════
 pitch-mcp is ready!
 Paste one of the snippets below into your LLM client config, then restart it.
═══════════════════════════════════════════════════════════════════════════════

── Claude Desktop (~/.config/claude/claude_desktop_config.json) ──────────────
{
  "mcpServers": {
    "pitch": {
      "command": "uvx",
      "args": ["pitch-mcp"]
    }
  }
}

── Cursor (~/.cursor/mcp.json or .cursor/mcp.json in your workspace) ─────────
{
  "mcpServers": {
    "pitch": {
      "command": "uvx",
      "args": ["pitch-mcp"]
    }
  }
}

── Generic MCP stdio (Windsurf, VS Code + Continue, Zed, etc.) ───────────────
  command : uvx
  args    : ["pitch-mcp"]

═══════════════════════════════════════════════════════════════════════════════
 If uvx is not found after restarting your client, add this to the config:
   "env": { "PATH": "/home/<your-username>/.local/bin:/usr/bin:/bin" }
═══════════════════════════════════════════════════════════════════════════════
EOF
