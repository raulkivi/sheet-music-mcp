# pitch-mcp — Troubleshooting

## Common problems

| Symptom | Cause | Fix |
|---------|-------|-----|
| `uvx: command not found` | `uv` not installed | Re-run `install.sh` |
| Server not appearing in LLM client | Config JSON has a syntax error | Validate the JSON file (e.g. paste into [jsonlint.com](https://jsonlint.com)) |
| LLM client says "server disconnected" | Server crashed at startup | Open a terminal, run `uvx pitch-mcp` manually and read the error |

## pitch-mcp-specific problems

| Symptom | Cause | Fix |
|---------|-------|-----|
| Real-time microphone fails to start | `libportaudio2` missing | Run `sudo apt install libportaudio2` |
| Pitch detection is inaccurate | Background noise or poor microphone | Use a quiet room and a close-mic setup |
| `SESSION_NOT_FOUND` with "timed out after N minutes idle" | The session was idle longer than `PITCH_SESSION_IDLE_MINUTES` (default 10) and was closed | Call `stop_monitoring` for its summary, then `load_score` again. Raise `PITCH_SESSION_IDLE_MINUTES` (or set `0`) for longer pauses |
| `sounddevice` error at startup | PortAudio not found at runtime | Install `libportaudio2` even if the Python package installed cleanly: `sudo apt install libportaudio2` |
| `INVALID_PARAMETER`: "musicxml_path must be inside one of the allowed folders" | Score paths are read only inside the output root (`SHEET_MUSIC_OUTPUT_ROOT`, default the working directory), the client's MCP roots and `SHEET_MUSIC_INPUT_ROOTS` | Add the score's folder to `SHEET_MUSIC_INPUT_ROOTS`, or pass the score inline as `musicxml`. `audio_path` is not restricted |
