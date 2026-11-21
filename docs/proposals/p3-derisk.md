# P3 — De-risk the two silent failures

> Task breakdown: [tasks/p3-derisk.md](../tasks/p3-derisk.md)

## Why this comes before the UI

Both open debts share one property: **they fail without an error.**

- A build that quietly produces a CPU binary makes every measurement the console
  would display a lie.
- A `down` that kills by process name can stop the server the console is talking
  to, and the operator reads it as "the UI is broken".

Shipping a console on top of either is decorating a floor you have not checked.

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

`up()` already writes `out/engine.pid`. **Acceptance:** with two servers on two
ports, `down` stops only the pid it started and leaves the other running.

## Scope guard
No new features in this phase. If a fix needs a redesign, it becomes its own
proposal — the point here is to remove two traps with the smallest correct
change.

## Definition of done
`runtime build --backend cuda --force` works unattended; `down` is targeted;
both `[DEBT]` markers are gone from the code and from the roadmap table; the
build and stop behaviour is covered by tests.
