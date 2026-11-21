# P6 — Operational polish

Five items, each with a reason and a testable result. None of them adds a
feature; all of them remove a way to be surprised.

## 1. `[DEBT] builder-cuda-prefix` — teach the builder the local cuFFT prefix
`voice-forge runtime build` currently configures a CPU build. The CUDA binary was
built by hand against `dist/cuda/usr` because CMake needs both
`CUDAToolkit_ROOT`-style library paths and explicit `-I` flags.

- Detect `dist/cuda/usr/{lib64,include}` and add the flags automatically.
- **Acceptance:** `runtime build --backend cuda --force` produces a binary that
  reports `backends: cpu,cuda` without any manual flag.

## 2. `[DEBT] server-kill-by-name` — kill the pid we started
`down()` runs `pkill -x audiocpp_server`, which kills any instance on the box.

- Track the pid returned by `up()` (already written to `out/engine.pid`) and
  signal that process group only.
- **Acceptance:** with two servers on different ports, `down` stops only ours.

## 3. Prune `dist/` build trees
9.7 GB of CMake trees are rebuildable; the binaries are 219 MB.

- Provide `voice-forge runtime clean --build-trees` (never touches `dist/bin` or
  `dist/cuda`).
- **Acceptance:** after cleaning, `render` still works and `runtime status`
  still reports the built backend.

## 4. CI
`uv run pytest` is the only gate and nothing runs it automatically.

- A workflow that runs `uv sync --extra dev && uv run pytest -q` on push.
- **Acceptance:** a broken test blocks the merge, not the operator's memory.

## 5. Preview retention — **done**
Resolved with the three-slot rotation (`slot-0..2.wav`, oldest overwritten).
Constant size by construction; no retention job needed. Documented in
[p3-ui.md](p3-ui.md#2-preview).

## Order
1 → 2 → 3 → 4. The first two protect against silent wrongness; the third
reclaims disk; the fourth protects the future.
