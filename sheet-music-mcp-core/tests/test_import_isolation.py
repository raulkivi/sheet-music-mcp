"""Engines may import the MCP-free modules without pulling in the MCP stack
(CLAUDE.md: engine.py must not import from mcp)."""

import subprocess
import sys
from importlib.metadata import version as package_version

import sheet_music_mcp_core


def test_mcp_free_modules_do_not_import_mcp_or_music21():
    code = (
        "import sys\n"
        "import sheet_music_mcp_core.errors, sheet_music_mcp_core.parts\n"
        "import sheet_music_mcp_core.params, sheet_music_mcp_core.annotations\n"
        "import sheet_music_mcp_core.paths, sheet_music_mcp_core.scores\n"
        "import sheet_music_mcp_core.measures\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('mcp', 'music21')))\n"
    )

    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "[]"


def test_version_matches_package_metadata():
    assert sheet_music_mcp_core.__version__ == package_version("sheet-music-mcp-core")
