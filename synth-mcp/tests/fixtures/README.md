# Test Fixtures

## Static fixtures

Small hand-written MusicXML scores for the practice-track and `starting_pitches` tests:

| File | Content |
|------|---------|
| `satb_4bars.musicxml` | SATB, 4 bars of 4/4 whole notes, D major; tempo 90 in bar 1 and 120 in bar 3 (top part only); first notes S D5, A A4, T F#4, B D3 |
| `six_eight.musicxml` | One part, 2 bars of 6/8 in dotted quarters, `<sound tempo="90"/>` |
| `pickup_sound_tempo.musicxml` | One part, 3/4 with a one-beat pickup (`implicit="yes"`), tempo only as a bare `<sound tempo="84"/>` |

Integration tests use MXL files from the shared sample set:

```
../../omr-mcp/test_samples/pdmx_satb_samples/mxl/   # 10 SATB MusicXML files
```

## Generated fixtures

If a WAV fixture is needed for future tests, generate it from a sample MXL and commit it here.
Run integration tests first to produce one:

```bash
uv run pytest tests/ -v -m integration
```
