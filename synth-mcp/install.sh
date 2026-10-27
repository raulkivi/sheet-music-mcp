#!/usr/bin/env bash
# synth-mcp/install.sh — sets up synth-mcp on Ubuntu / Debian / Linux Mint
#
# After this script finishes, paste the printed config snippet into your LLM
# client (Claude Desktop, Cursor, etc.) and restart it to start using synth-mcp.
#
# Usage:
#   bash synth-mcp/install.sh      # from repo root
#   ./install.sh                   # from inside synth-mcp/

set -euo pipefail

# ── colours ──────────────────────────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC}  $*"; }
warn() { echo -e "${YELLOW}!${NC}  $*"; }
die()  { echo -e "${RED}Error:${NC} $*" >&2; exit 1; }

# ── paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BOLD}synth-mcp installer${NC}"
echo "════════════════════════════════════════"
echo ""

# ── 1. verify apt-based distro ───────────────────────────────────────────────
if ! command -v apt-get &>/dev/null && [[ ! -f /etc/debian_version ]]; then
    die "This script requires an apt-based Linux distro (Ubuntu, Debian, Linux Mint).
       synth-mcp can still work on other systems — install libfluidsynth-dev
       manually, then paste the config snippet below into your LLM client."
fi

# ── 2. require uv ─────────────────────────────────────────────
echo -e "${CYAN}[1/4]${NC} Checking for uv..."
if command -v uv &>/dev/null; then
    ok "uv already installed  ($(uv --version 2>&1 | head -1))"
else
    die "uv is not installed.  Install it, then re-run this script:
       https://docs.astral.sh/uv/getting-started/installation/"
fi

# ── 3. install system packages ───────────────────────────────────────────────
echo ""
echo -e "${CYAN}[2/4]${NC} Installing system packages (requires sudo)..."
sudo apt-get update -qq
sudo apt-get install -y libfluidsynth-dev
ok "libfluidsynth-dev installed"

# ── 4. set up the Python venv via uv sync ────────────────────────────────────
echo ""
echo -e "${CYAN}[3/4]${NC} Setting up Python environment in ${SCRIPT_DIR}..."
(cd "$SCRIPT_DIR" && uv sync)
ok "Python environment ready"

# ── 5. find or download a SoundFont ──────────────────────────────────────────
echo ""
echo -e "${CYAN}[4/4]${NC} Looking for a SoundFont (.sf2)..."

SOUNDFONT_PATH=""

# check well-known locations (first match wins)
for candidate in \
    "$HOME/.local/share/sounds/sf2/TimGM6mb.sf2"    \
    "$HOME/.local/share/sounds/sf2/default-GM.sf2"  \
    "/usr/share/sounds/sf2/TimGM6mb.sf2"             \
    "/usr/share/sounds/sf2/default-GM.sf2"           \
    "/usr/share/sounds/sf2/FluidR3_GM.sf2"           \
    "/usr/share/sounds/sf2/FluidR3Mono_GM.sf3"       \
; do
    if [[ -f "$candidate" ]]; then
        SOUNDFONT_PATH="$candidate"
        break
    fi
done

# also scan the sf2 dirs for any .sf2 we may have missed
if [[ -z "$SOUNDFONT_PATH" ]]; then
    for sf_dir in "/usr/share/sounds/sf2" "$HOME/.local/share/sounds/sf2"; do
        if [[ -d "$sf_dir" ]]; then
            first_sf2=$(ls "$sf_dir"/*.sf2 2>/dev/null | head -1 || true)
            if [[ -n "$first_sf2" ]]; then
                SOUNDFONT_PATH="$first_sf2"
                break
            fi
        fi
    done
fi

if [[ -n "$SOUNDFONT_PATH" ]]; then
    ok "SoundFont found: $SOUNDFONT_PATH"
else
    # Try the apt package first (most reliable on Ubuntu/Debian)
    SF_APT_PATH="/usr/share/sounds/sf2/TimGM6mb.sf2"
    echo "     No SoundFont found.  Trying to install timgm6mb-soundfont package..."
    if sudo apt-get install -y timgm6mb-soundfont 2>/dev/null \
            && [[ -f "$SF_APT_PATH" ]]; then
        SOUNDFONT_PATH="$SF_APT_PATH"
        ok "SoundFont installed via apt: $SOUNDFONT_PATH"
    else
        # Fall back to a direct download into the user's home dir
        SF_DIR="$HOME/.local/share/sounds/sf2"
        SF_TARGET="$SF_DIR/TimGM6mb.sf2"
        mkdir -p "$SF_DIR"
        echo "     Downloading TimGM6mb.sf2 (~5.7 MB) to $SF_TARGET ..."
        if curl -L --progress-bar \
            "https://sourceforge.net/projects/fluidsynth/files/Demo%20Music/TimGM6mb.sf2/download" \
            -o "$SF_TARGET" \
            && [[ -s "$SF_TARGET" ]]; then
            SOUNDFONT_PATH="$SF_TARGET"
            ok "SoundFont downloaded to: $SOUNDFONT_PATH"
        else
            rm -f "$SF_TARGET"
            warn "Automatic download failed."
            warn "Download TimGM6mb.sf2 manually and place it at: $SF_TARGET"
            warn "Free soundfonts: https://musescore.org/en/handbook/3/soundfonts-and-sfz-files"
            # use the target path so the config snippet is still useful
            SOUNDFONT_PATH="$SF_TARGET"
        fi
    fi
fi

# ── 6. print ready-to-paste config snippets ───────────────────────────────────
echo ""
echo -e "${BOLD}════════════════════════════════════════${NC}"
echo -e "${BOLD}Setup complete!${NC}"
echo ""
echo "Paste one of the snippets below into your LLM client and restart it."
echo "The SYNTH_SOUNDFONT_PATH value has been filled in automatically."
echo ""

echo -e "${BOLD}▸ Claude Desktop${NC}  (~/.config/claude/claude_desktop_config.json)"
echo ""
cat <<SNIPPET
{
  "mcpServers": {
    "synth": {
      "command": "uvx",
      "args": ["synth-mcp"],
      "env": {
        "SYNTH_SOUNDFONT_PATH": "${SOUNDFONT_PATH}"
      }
    }
  }
}
SNIPPET

echo ""
echo -e "${BOLD}▸ Cursor${NC}  (~/.cursor/mcp.json  or  .cursor/mcp.json in your project)"
echo ""
cat <<SNIPPET
{
  "mcpServers": {
    "synth": {
      "command": "uvx",
      "args": ["synth-mcp"],
      "env": {
        "SYNTH_SOUNDFONT_PATH": "${SOUNDFONT_PATH}"
      }
    }
  }
}
SNIPPET

echo ""
echo -e "Need a different soundfont? See ${CYAN}synth-mcp/docs/soundfonts.md${NC} (coming soon)."
echo -e "Something not working?  Check ${CYAN}synth-mcp/TROUBLESHOOTING.md${NC} (coming soon)."
echo ""
