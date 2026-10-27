#!/usr/bin/env bash
# musicxml-abc-mcp/install.sh — set up musicxml-abc-mcp on Ubuntu / Debian / Linux Mint
# After running this script, paste the printed config snippet into your LLM client.

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${GREEN}[musicxml-abc-mcp]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[musicxml-abc-mcp]${RESET} $*"; }
error()   { echo -e "${RED}[musicxml-abc-mcp] ERROR:${RESET} $*" >&2; }

# ── 1. Verify apt-based distro ────────────────────────────────────────────────
if ! [ -f /etc/debian_version ] && ! command -v apt &>/dev/null; then
    error "This script requires an apt-based Linux distribution."
    error "Supported: Ubuntu, Debian, Linux Mint."
    error "Your system does not appear to be apt-based — exiting."
    exit 1
fi

info "Detected apt-based system. Continuing."

# ── 2. Require uv ─────────────────────────────────────
if command -v uv &>/dev/null; then
    info "uv is already installed: $(uv --version)"
else
    error "uv is not installed. Install it, then re-run this script:"
    error "  https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

# ── 3. System apt packages ────────────────────────────────────────────────────
# musicxml-abc-mcp has no required apt packages.
# It is pure Python (music21 + custom ABC serializer) — no system libraries needed.
info "No apt packages required for musicxml-abc-mcp."

# ── 4. Create the server venv via uv sync ────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info "Running 'uv sync --extra dev' in ${SCRIPT_DIR} ..."
(cd "$SCRIPT_DIR" && uv sync --extra dev)
info "Python environment ready."

# ── 5. Print ready-to-paste config snippets ──────────────────────────────────
echo
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║          musicxml-abc-mcp is ready to use                    ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo

echo -e "${BOLD}── Claude Desktop ───────────────────────────────────────────────${RESET}"
echo "Config file: ~/.config/claude/claude_desktop_config.json"
echo
echo '  {'
echo '    "mcpServers": {'
echo '      "musicxml-abc": {'
echo '        "command": "uvx",'
echo '        "args": ["musicxml-abc-mcp"]'
echo '      }'
echo '    }'
echo '  }'
echo

echo -e "${BOLD}── Cursor ───────────────────────────────────────────────────────${RESET}"
echo "Config file: ~/.cursor/mcp.json"
echo
echo '  {'
echo '    "mcpServers": {'
echo '      "musicxml-abc": {'
echo '        "command": "uvx",'
echo '        "args": ["musicxml-abc-mcp"]'
echo '      }'
echo '    }'
echo '  }'
echo

echo -e "${BOLD}── Other MCP clients (generic stdio) ────────────────────────────${RESET}"
echo '  command: uvx'
echo '  args:    ["musicxml-abc-mcp"]'
echo

info "Done. Paste one of the snippets above into your LLM client config and restart it."
