# P3 — De-risk: task breakdown

Spec: [../proposals/p3-derisk.md](../proposals/p3-derisk.md) · Four silent
failures, nine tasks.

**Status: done (2026-11-23).** Every task below passed its own check; the
evidence per task is recorded in [Result](#result-2026-11-23).

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P3-1 | `RuntimeBuilder`: if `dist/cuda/usr/{lib64,include}` exist, add `CUDAToolkit_ROOT`, `CMAKE_CUDA_COMPILER`, `CMAKE_LIBRARY_PATH`, `CMAKE_INCLUDE_PATH` and both `-I` flags | `adapters/secondary/runtime_builder.py` | Fake-runner test asserts every flag in the configure command | M |
| P3-2 | Prove it for real: rebuild CUDA through the builder and check the backend | `dist/` (gitignored) | `runtime build --backend cuda --force` → `audiocpp_cli --version` reports `backends: cpu,cuda`; a render still works | M |
| P3-3 | Remove the builder marker from the code and its row from the roadmap | `runtime_builder.py`, `docs/roadmap.md` | `grep -r "DEBT. builder"` returns nothing | S |
| P3-4 | Persist the pid from `up()` (today only the qwen supervisor does) and signal that pid group in `down()`, instead of `pkill -x` | `adapters/secondary/audiocpp_server.py` | Two servers on two ports: `down` stops one, the other keeps answering `/health` | M |
| P3-5 | Remove the kill-by-name marker from the code and its row from the roadmap | code + `docs/roadmap.md` | `grep` empty | S |
| P3-6 | Changelog + roadmap status; note that `runtime build` is safe again | `docs/` | Docs match behaviour | S |
| P3-7 | Stop blocking the event loop: make the render/wait handlers plain `def` so Starlette runs them in its threadpool, or offload the `queue.wait(...)` | `adapters/primary/http.py` | while a render runs, `GET /api/queue` answers with `busy: true`; `uv run pytest -q` green | S |
| P3-8 | Make admission cross processes: add the `JobState` port + `FileJobState` (`flock` on `out/active-job.lock` held for the job, atomic `out/active-job.json`), wire it into `SerialQueue` (`busy`, `snapshot`) and make `down` / `queue` read it | `application/ports.py`, `application/queue.py`, `adapters/secondary/fs_job_state.py`, `container.py` | render in one process, `down` in another → exit 2 and the render still finishes | M |
| P3-9 | Ownership token + pidfd in `down`: `up` writes a random token into the server environment and the pid file; `down` opens a pidfd, verifies the boot token in `/proc/<pid>/environ`, then signals through that same descriptor (drop `killpg`/`getpgid`/name matching); only wait on `/shutdown` when the endpoint answers below 400 | `adapters/secondary/pid_signal.py`, `adapters/secondary/audiocpp_server.py`, `adapters/secondary/engine_process.py` | a foreign live `sleep` in the pid file survives `down`; a real server stops in under 1 s | M |

## Order
P3-1 → P3-2 (the proof is the point) → P3-3 → P3-4 → P3-5 → P3-6 → P3-7 → P3-8 → P3-9.
Do not mark P3-1 done on the unit test alone: P3-2 is what proves the flags are
the right ones on this machine.

## Result (2026-11-23)

| # | Check | Outcome |
|---|---|---|
| P3-1 | Fake-runner test asserts every flag | ✅ passed — the configure command carries `CUDAToolkit_ROOT`, `CMAKE_CUDA_COMPILER`, `CMAKE_LIBRARY_PATH`, `CMAKE_INCLUDE_PATH` and both `-I` flags |
| P3-2 | `runtime build --backend cuda --force` → `backends: cpu,cuda`, render still works | ✅ passed — unattended build, `EXIT=0`, `action: built` in ~21 min; both new binaries report `backends: cpu,cuda`; `warm` + a two-line render followed |
| P3-3 | `grep -r "DEBT. builder"` returns nothing | ✅ passed — no open builder marker survives in code or the roadmap |
| P3-4 | `down` stops one server, the other keeps answering | ✅ passed by unit test — `down` signals only the pid in `out/server.pid`; the live pair was not run (see the proposal's Outcome) |
| P3-5 | `grep` empty for the marker | ✅ passed — no open kill-by-name marker survives in code or docs |
| P3-6 | Docs match behaviour | ✅ passed — roadmap, proposal, this list, changelog `0.14.0`, `context.md`, `architecture.md` and the README describe the builder-owned build |
| P3-7 | `GET /api/queue` answers during a render; `pytest -q` green | ✅ passed — handlers are sync `def`; the concurrency test was red against the old `async def` handler and green after; 108 tests pass |
| P3-8 | Render in one process, `down` in another → exit 2, render finishes | ✅ passed — `voice-forge queue` from a second process reported `busy: true` with `active: {kind: render, pid: 72528}`; `voice-forge down` exited 2 ("a job is running; wait for it or use `down --force`") while the render ran to exit 0 in 32.0 s / 10 lines; the final `down` exited 0 and removed `out/server.pid` + `out/active-job.json`; 114 tests pass |
| P3-9 | Foreign live `sleep` survives `down`; a real server stops in under 1 s | ✅ passed — a foreign `sleep` left running in the pid file with a fake token: `down` exit 0 with `via: "garbage"`, the `sleep` still alive; a real server: `down` exit 0 in 0.2 s, pid file removed; TERM → `wait(15)` → KILL → `wait(5)` on one pidfd, verified by `select`, never `os.kill(pid, 0)`; 143 tests pass (128 before this task) |

## Definition of done
`runtime build --backend cuda --force` needs no manual step; `down` cannot touch
a server it did not start, and it refuses a job started by any process;
`GET /api/queue` answers while a render runs; zero open `[DEBT]` markers left in
code or the roadmap, and the docs' temporary P3 pointers removed.
