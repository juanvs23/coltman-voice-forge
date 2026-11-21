# P7 — Operational polish

> Task breakdown: [tasks/p7-ops.md](../tasks/p7-ops.md)

Two items that keep the project cheap to live with. The three items originally
planned here moved: the build and stop defects became [P3](p3-derisk.md), and
preview retention was solved with the three-slot rotation
([P4](p4-ui.md#2-preview)).

## 1. Prune `dist/` build trees

`dist/` is 11 GB: 219 MB of binaries, 279 MB of local cuFFT, 1.7 GB model, and
~9.7 GB of CMake trees that exist only to make a rebuild incremental.

- `voice-forge runtime clean --build-trees` deletes `dist/build*` only. It must
  never touch `dist/bin` or `dist/cuda`.
- **Acceptance:** after cleaning, a render still works, `runtime status` still
  reports the built backend, and `runtime build` can rebuild if asked.

## 2. CI

`uv run pytest` is the only gate, and nothing runs it automatically.

- Workflow: `uv sync --extra dev` then `uv run pytest -q`, on push and PR.
- No GPU needed: the suite is designed to run without models.
- **Acceptance:** a deliberately broken test blocks the merge.

## Why last
Neither item can make the system lie; they only cost disk and memory. Everything
above them either protects correctness (P3) or adds capability (P4–P6).

## Definition of done
A `clean` command that reclaims ~9.7 GB without breaking a render, and a CI check
that fails on regression.
