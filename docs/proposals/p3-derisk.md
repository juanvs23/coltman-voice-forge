# P3 — De-risk the three silent failures

> Task breakdown: [tasks/p3-derisk.md](../tasks/p3-derisk.md)

## Why this comes before the UI

All open debts share one property: **they fail without an error.**

- A build that quietly produces a CPU binary makes every measurement the console
  would display a lie.
- A `down` that kills by process name can stop the server the console is talking
  to, and the operator reads it as "the UI is broken".
- An API whose handlers block the event loop cannot report progress, so the
  console's "watch the queue while it renders" screen shows a spinner that never
  moves.

Shipping a console on top of any of them is decorating a floor you have not
checked.

## Debt 1 — `[DEBT] builder-cuda-prefix`

`RuntimeBuilder` configures a CPU build. The CUDA binary exists only because it
was built by hand:

```bash
dnf download --destdir dist/rpms libcufft-devel libcufft
cd dist/cuda && rpm2cpio ../rpms/libcufft-*.rpm | cpio -idm
cmake -S dist/src/audio.cpp -B dist/build-cuda \
  -DENGINE_ENABLE_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89 \
  -DCMAKE_CUDA_COMPILER=/usr/bin/nvcc \
  -DCMAKE_LIBRARY_PATH=$PWD/dist/cuda/usr/lib64 \
  -DCMAKE_INCLUDE_PATH=$PWD/dist/cuda/usr/include \
  -DCMAKE_CUDA_FLAGS="-I$PWD/dist/cuda/usr/include" \
  -DCMAKE_CXX_FLAGS="-I$PWD/dist/cuda/usr/include"
```

Two things were learned the hard way and must live in the builder:
1. `CMAKE_LIBRARY_PATH` lets `FindCUDAToolkit` link, but **does not export the
   include directory**; without `-I` on both `CMAKE_CUDA_FLAGS` and
   `CMAKE_CXX_FLAGS`, `nvcc` dies on `#include <cufft.h>` at 98 %.
2. On Fedora/Nobara the libraries land in `/usr/lib64`, not
   `/usr/local/cuda/lib64` — the probe already checks both.

**Acceptance:** `voice-forge runtime build --backend cuda --force` on this
machine produces a binary whose `--version` reports `backends: cpu,cuda`, with
no manual flags.

## Debt 2 — `[DEBT] server-kill-by-name`

`down()` runs `pkill -x audiocpp_server`. With one server on one port this is
invisible; the moment a second instance exists (a comparison, a second project),
`down` stops the wrong one.

Only the Qwen supervisor writes `out/engine.pid` today; the default `audiocpp`
adapter does not, so the fix starts by persisting it. **Acceptance:** with two
servers on two ports, `down` stops only the pid it started and leaves the other
running.

## Defect 3 — the API blocks the event loop

The HTTP handlers are `async def` but call the blocking `queue.wait(...)`
directly. With a single uvicorn worker the coroutine never yields, so the event
loop is stalled for the whole render: `GET /api/queue` cannot answer, and the
console cannot show `busy` or a pending count while work is in flight.

This invalidates the P4 acceptance criterion "watch the queue state while it
runs", and it is invisible in tests because the test client talks to the app
without a live loop under load.

Same class of failure as the other two: no exception, no log line, just a client
that hangs.

**Acceptance:** with a render in progress, `GET /api/queue` answers and returns
`busy: true`; the handlers do not block the loop. The smallest correct fix is to
declare them `def` so Starlette runs them in its threadpool, or to offload the
`wait` — whichever keeps the queue semantics untouched.

## Scope guard
No new features in this phase. If a fix needs a redesign, it becomes its own
proposal — the point here is to remove three traps with the smallest correct
change.

## Definition of done
`runtime build --backend cuda --force` works unattended; `down` is targeted;
`GET /api/queue` answers during a render; all three `[DEBT]` markers are gone
from the code and from the roadmap table; the build, stop and request-path
behaviour is covered by tests.

## Outcome (2026-11-23)

All three closed. What shipped:

- **`RuntimeBuilder` detects the local toolkit prefix.** When
  `dist/cuda/usr/{lib64,include}` exist it adds `CUDAToolkit_ROOT`,
  `CMAKE_CUDA_COMPILER`, `CMAKE_LIBRARY_PATH`, `CMAKE_INCLUDE_PATH` and the two
  `-I` flags that `FindCUDAToolkit` does not export. A fake-runner unit test
  asserts every flag in the configure command.
- **The build was proven for real, not on the test alone.**
  `voice-forge runtime build --backend cuda --force` ran unattended for ~21 min
  and ended `EXIT=0` with `action: built`, `backend: cuda`. `dist/BUILD.json`
  records `cuda_prefix: .../dist/cuda/usr`, `cuda_compiler: /usr/bin/nvcc`,
  `cuda_arch: 89` and the eight flags. The new `audiocpp_cli` (99 MB) and
  `audiocpp_server` (107 MB, stripped) both report `backends: cpu,cuda`.
- **`down` is pid-scoped.** `up` persists `out/server.pid` as
  `{pid, port, started_at}`; `down` signals that pid group only (SIGTERM, then
  SIGKILL after 15 s) and raises `EngineBusy` while a job runs unless `--force`.
  Never matches by process name.
- **The event loop stays free.** Blocking request handlers are plain `def`, so
  Starlette runs them in its threadpool; the concurrency test was verified red
  against the old `async def` handler before the fix.

End-to-end run after the rebuild: `up` → pid 41376 with `out/server.pid` written;
`warm` 0.6 s; `render examples/dialogo.yaml` → 6.4 s for 2 lines; `down` →
`{"status":"down","pid":41376}`, which stopped only that pid and removed the pid
file. Full suite: **108 passed** (95 before), one pre-existing
Starlette/httpx deprecation warning.

Honest limit: the acceptance criterion "with two servers on two ports, `down`
stops only its own" is covered by a unit test — the file's pid is signalled and
nothing else — not by a live two-server experiment. No live pair was run, so
that line of evidence is still missing.

Disk after the work: `dist/` 12 GB — `dist/build` 9.7 GB (the new build tree),
`dist/build-cuda` 782 MB (the superseded hand build, prunable in P7),
`dist/src` 369 MB, `dist/cuda` 279 MB, `dist/bin` 197 MB, `dist/rpms` 177 MB.

