# Contributing

Thanks for helping improve sheet-music-mcp. This is a personal project
maintained on a best-effort basis, so replies may take a few days.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Report security problems privately as described in [SECURITY.md](SECURITY.md),
never in a public issue.

## Repository layout

Six independent Python packages, each with its own `pyproject.toml`, tests and
virtual environment: `omr-mcp`, `render-mcp`, `synth-mcp`, `musicxml-abc-mcp`,
`pitch-mcp` and `comparer-mcp`. See the [README](README.md) for what each one
does and [docs/conventions.md](docs/conventions.md) for the coding standards
all servers share.

## Getting started

You need Python 3.11+ (3.12+ for `pitch-mcp`) and [uv](https://docs.astral.sh/uv/).
Some servers also need system libraries (FluidSynth, Cairo, PortAudio); the
README lists them.

```sh
git clone https://github.com/raulkivi/sheet-music-mcp
cd sheet-music-mcp/synth-mcp        # or any other server
uv sync --extra dev
uv run pytest -m "not integration"  # what CI runs
```

Rules of thumb:

- Work inside one server's directory. Never share virtual environments between
  servers.
- Use `uv sync` and `uv add`, not `pip install`.
- Integration tests (`-m integration`) need the real OMR or audio backends and
  are optional locally.
- Each server has a `CLAUDE.md` and `.github/copilot-instructions.md` with
  status, gotchas and its definition of done. Read them before changing code.

## Making a change

1. Open an issue first for anything larger than a small fix, so we can agree on
   the approach before you invest time.
2. Fork the repo and create a branch from `main`.
3. Write a failing test, then the code that makes it pass.
4. Run the tests for every server you touched.
5. Update the relevant README, `SETUP.md` or `docs/` page if behavior changes.
6. Open a pull request using the template and describe what changed and why.

Pull requests run tests, CodeQL, a security review and
[unicode-smuggling-guard](https://github.com/raulkivi/unicode-smuggling-guard),
which rejects hidden Unicode characters in code, docs and agent files. Keep to
plain visible characters.

## Reporting bugs and requesting features

Use the issue forms. For bugs, include the server name and version, your OS,
your MCP client, and the output of the server's `health_check` tool.

## Releases

Maintainers release each server separately. See the Development section of the
[README](README.md) for the version bump and tag steps.

## License

Contributions are licensed under the [MIT License](LICENSE).
