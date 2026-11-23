# P3 — De-risk: task breakdown

Spec: [../proposals/p3-derisk.md](../proposals/p3-derisk.md) · Three silent
failures, seven tasks.

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P3-1 | `RuntimeBuilder`: if `dist/cuda/usr/{lib64,include}` exist, add `CUDAToolkit_ROOT`, `CMAKE_CUDA_COMPILER`, `CMAKE_LIBRARY_PATH`, `CMAKE_INCLUDE_PATH` and both `-I` flags | `adapters/secondary/runtime_builder.py` | Fake-runner test asserts every flag in the configure command | M |
| P3-2 | Prove it for real: rebuild CUDA through the builder and check the backend | `dist/` (gitignored) | `runtime build --backend cuda --force` → `audiocpp_cli --version` reports `backends: cpu,cuda`; a render still works | M |
| P3-3 | Remove `[DEBT] builder-cuda-prefix` from the code and its row from the roadmap | `runtime_builder.py`, `docs/roadmap.md` | `grep -r "DEBT. builder"` returns nothing | S |
| P3-4 | Persist the pid from `up()` (today only the qwen supervisor does) and signal that pid group in `down()`, instead of `pkill -x` | `adapters/secondary/audiocpp_server.py` | Two servers on two ports: `down` stops one, the other keeps answering `/health` | M |
| P3-5 | Remove `[DEBT] server-kill-by-name` from the code and its row from the roadmap | code + `docs/roadmap.md` | `grep` empty | S |
| P3-6 | Changelog + roadmap status; note that `runtime build` is safe again | `docs/` | Docs match behaviour | S |
| P3-7 | Stop blocking the event loop: make the render/wait handlers plain `def` so Starlette runs them in its threadpool, or offload the `queue.wait(...)` | `adapters/primary/http.py` | while a render runs, `GET /api/queue` answers with `busy: true`; `uv run pytest -q` green | S |

## Order
P3-1 → P3-2 (the proof is the point) → P3-3 → P3-4 → P3-5 → P3-6 → P3-7.
Do not mark P3-1 done on the unit test alone: P3-2 is what proves the flags are
the right ones on this machine.

## Definition of done
`runtime build --backend cuda --force` needs no manual step; `down` cannot touch
a server it did not start; `GET /api/queue` answers while a render runs; zero
`[DEBT]` markers left in the tree, and the docs' temporary P3 pointers removed.
