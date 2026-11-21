# P6 — Operational polish: task breakdown

Spec: [../proposals/p6-ops.md](../proposals/p6-ops.md)

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P6-1 | `RuntimeBuilder`: detect `dist/cuda/usr/{lib64,include}` and add `CUDAToolkit_ROOT`, `CMAKE_CUDA_COMPILER`, `CMAKE_CUDA_FLAGS`/`CMAKE_CXX_FLAGS` `-I`, `CMAKE_LIBRARY_PATH` | `adapters/secondary/runtime_builder.py` | Fake-runner test asserts every flag; then `runtime build --backend cuda --force` reports `backends: cpu,cuda` | M |
| P6-2 | Remove the `[DEBT] builder-cuda-prefix` marker and its roadmap row once P6-1 lands | code + `docs/roadmap.md` | `grep -r "\[DEBT\] builder"` is empty | S |
| P6-3 | `AudiocppServerControl.down()` signals the pid it started (read `out/engine.pid`), not `pkill -x` | `adapters/secondary/audiocpp_server.py` | Two servers on two ports: `down` stops only ours | M |
| P6-4 | Remove the `[DEBT] server-kill-by-name` marker and its row | code + `docs/roadmap.md` | `grep` empty | S |
| P6-5 | `voice-forge runtime clean --build-trees` deletes only `dist/build*`, never `dist/bin` or `dist/cuda` | `runtime_builder.py`, `cli.py` | After cleaning, `render` works and `runtime status` reports the built backend | S |
| P6-6 | CI workflow: `uv sync --extra dev && uv run pytest -q` on push | `.github/workflows/ci.yml` | A deliberately broken test blocks the merge | S |
| P6-7 | Docs: changelog + roadmap phases marked done | `docs/` | Docs match behaviour | S |

## Order and why
1 → 3 → 5 → 6. The first two remove ways of being silently wrong; the third
reclaims ~9.7 GB; the last protects the future.

## Definition of done
`runtime build --backend cuda --force` works with no manual flags; `down` is
targeted; `dist/` prunable; CI green on push.
