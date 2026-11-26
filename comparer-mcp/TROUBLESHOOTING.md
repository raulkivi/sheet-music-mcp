# comparer-mcp — Troubleshooting

**Last changed:** 2026-11-26 · **Source:** https://github.com/raulkivi/sheet-music-mcp

| Symptom | Cause | Fix |
|---------|-------|-----|
| `uvx: command not found` | `uv` not installed | Re-run `install.sh` |
| Server not appearing in LLM client | Config JSON has a syntax error | Validate the JSON file (e.g. paste into jsonlint.com) |
| LLM client says "server disconnected" | Server crashed at startup | Open a terminal, run `uvx comparer-mcp` manually and read the error |
| `error_code: INVALID_INPUT` on `compare_scores` | Input string is not MusicXML | Confirm the string contains a `<score-partwise>` or `<score-timewise>` root element |
| `error_code: FILE_NOT_FOUND` on `compare_scores` with a `*_path` parameter | Path doesn't exist, or a relative path was resolved against the output folder | Use an absolute path |
| `error_code: INVALID_PARAMETER`, "must be inside one of the allowed folders" | The file is outside the folders the server may read (the output folder, the client's roots, `SHEET_MUSIC_INPUT_ROOTS`) | Move the file into one of them, or add its folder to `SHEET_MUSIC_INPUT_ROOTS` in the server's `env` config |
| `error_code: INVALID_PARAMETER` on `compare_scores` for a `.pdf` or other file | Only `.musicxml`, `.xml` and `.mxl` are read | Convert the score to MusicXML first (omr-mcp for images) |
| `export_annotated_musicxml` returns `*_path` fields instead of MusicXML | Large results are written to files (`return: "auto"`) | Pass the paths to render-mcp as `musicxml_path`, or call with `return: "inline"` to get the text |
| `similarity_score` lower than expected | Parts matched positionally instead of by name, or measure numbers don't line up | Check `part_diffs[].measures_missing` / `measures_extra` first — a structural mismatch skews the score more than any single wrong note |
| `compare_scores` with `detail: "changes"` returns nothing but you expect differences | `parts` matches IDs, names or voices, and `measures` covers only the bars you list | Call with `detail: "full"` first and inspect `part_diffs[].part_name` |
| Comparison is slow on a large orchestral score | No hard timeout is enforced (see `docs/requirements.md` NFR-3) | Expected for large scores; consider `detail: "summary"` first if you don't need note-level detail |
