#!/usr/bin/env bash
# render-mcp/install.sh — set up render-mcp on Ubuntu / Debian / Linux Mint
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

# ── 3. Install system dependencies ────────────────────────────────────────────
echo "→ Installing system libraries (requires sudo)..."
sudo apt-get update -qq
sudo apt-get install -y libcairo2
echo "✓ libcairo2 installed"

# ── 4. Set up the server venv ─────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "→ Running uv sync in $SCRIPT_DIR..."
cd "$SCRIPT_DIR"
uv sync
echo "✓ render-mcp venv ready"

# ── 5. Print config snippets ──────────────────────────────────────────────────
cat <<'EOF'

═══════════════════════════════════════════════════════════════════════════════
 render-mcp is ready!
 Paste one of the snippets below into your LLM client config, then restart it.
═══════════════════════════════════════════════════════════════════════════════

── Claude Desktop (~/.config/claude/claude_desktop_config.json) ──────────────
{
  "mcpServers": {
    "render": {
      "command": "uvx",
      "args": ["render-mcp"]
    }
  }
}

── Cursor (~/.cursor/mcp.json or .cursor/mcp.json in your workspace) ─────────
{
  "mcpServers": {
    "render": {
      "command": "uvx",
      "args": ["render-mcp"]
    }
  }
}

── Generic MCP stdio (Windsurf, VS Code + Continue, Zed, etc.) ───────────────
  command : uvx
  args    : ["render-mcp"]

═══════════════════════════════════════════════════════════════════════════════
 If uvx is not found after restarting your client, add this to the config:
   "env": { "PATH": "/home/<your-username>/.local/bin:/usr/bin:/bin" }
═══════════════════════════════════════════════════════════════════════════════
EOF
