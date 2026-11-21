# P7 — Operational polish: task breakdown

Spec: [../proposals/p7-ops.md](../proposals/p7-ops.md)

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P7-1 | `voice-forge runtime clean --build-trees` deletes only `dist/build*`; refuses to touch `dist/bin` or `dist/cuda` | `adapters/secondary/runtime_builder.py`, `cli.py` | After cleaning: `render` works, `runtime status` still reports `cuda` | S |
| P7-2 | Report reclaimed bytes and the paths kept | `cli.py` | Output names each removed path and the total freed | S |
| P7-3 | CI workflow: `uv sync --extra dev && uv run pytest -q` on push/PR | `.github/workflows/ci.yml` | A deliberately broken test fails the check | S |
| P7-4 | Docs: changelog, roadmap status | `docs/` | Docs match behaviour | S |

## Notes
- Cleaning is destructive, so it is a **command**, never automatic on start.
- The model (`models/ming3`, 1.7 GB) and `dist/cuda` (279 MB) are needed at run
  time; the clean command must say so in its output rather than letting the
  operator discover it later.

## Definition of done
~9.7 GB reclaimed on demand with one command, and a regression can no longer
reach main unnoticed.
