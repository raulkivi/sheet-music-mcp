#!/usr/bin/env bash
# omr-mcp/install.sh — set up omr-mcp on Ubuntu / Debian / Linux Mint
# After running this script, paste the printed config snippet into your LLM client.

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${GREEN}[omr-mcp]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[omr-mcp]${RESET} $*"; }
error()   { echo -e "${RED}[omr-mcp] ERROR:${RESET} $*" >&2; }

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
# omr-mcp has no required apt packages for the default engine.
# oemer (the default OCR engine) is pure Python + ONNX — no system libraries needed.
# The optional engine="audiveris" (better multi-staff/SATB support) needs dpkg-deb to extract its
# self-contained download, which ships with dpkg — already present on virtually all Debian/Ubuntu
# systems, so nothing extra to install here either.
info "No apt packages required for omr-mcp."

# ── 4. Create the server venv via uv sync ────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info "Running 'uv sync' in ${SCRIPT_DIR} ..."
(cd "$SCRIPT_DIR" && uv sync)
info "Python environment ready."

# ── 5. Print ready-to-paste config snippets ──────────────────────────────────
echo
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║              omr-mcp is ready to use                        ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo
echo -e "${BOLD}IMPORTANT — first-run note:${RESET}"
echo "  The first time a tool is called, omr-mcp downloads ~100 MB of"
echo "  ONNX model checkpoints. This happens once and takes ~5 minutes."
echo "  Subsequent runs use the cached models."
echo "  If you use engine=\"audiveris\" (better for multi-staff SATB choir scores),"
echo "  its first use downloads a separate ~80 MB self-contained engine."
echo

echo -e "${BOLD}── Claude Desktop ───────────────────────────────────────────────${RESET}"
echo "Config file: ~/.config/claude/claude_desktop_config.json"
echo
echo '  {'
echo '    "mcpServers": {'
echo '      "omr": {'
echo '        "command": "uvx",'
echo '        "args": ["omr-mcp"]'
echo '      }'
echo '    }'
echo '  }'
echo

echo -e "${BOLD}── Cursor ───────────────────────────────────────────────────────${RESET}"
echo "Config file: ~/.cursor/mcp.json"
echo
echo '  {'
echo '    "mcpServers": {'
echo '      "omr": {'
echo '        "command": "uvx",'
echo '        "args": ["omr-mcp"]'
echo '      }'
echo '    }'
echo '  }'
echo

echo -e "${BOLD}── Other MCP clients (generic stdio) ────────────────────────────${RESET}"
echo '  command: uvx'
echo '  args:    ["omr-mcp"]'
echo

info "Done. Paste one of the snippets above into your LLM client config and restart it."
