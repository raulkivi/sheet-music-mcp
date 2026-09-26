"""server.json must match the package, or the MCP Registry rejects the publish."""

import json
from importlib.metadata import version as package_version
from pathlib import Path

PACKAGE = "musicxml-abc-mcp"
ROOT = Path(__file__).resolve().parent.parent


def _server_json():
    return json.loads((ROOT / "server.json").read_text())


def test_versions_match_package():
    server = _server_json()
    assert server["version"] == package_version(PACKAGE)
    assert [p["version"] for p in server["packages"]] == [package_version(PACKAGE)]


def test_points_to_pypi_package():
    [package] = _server_json()["packages"]
    assert (package["registryType"], package["identifier"]) == ("pypi", PACKAGE)


def test_readme_declares_registry_name():
    # The registry proves PyPI ownership by finding this marker in the published README.
    assert f"<!-- mcp-name: {_server_json()['name']} -->" in (ROOT / "README.md").read_text()
