# P4 — Derive by timbre: task breakdown

Spec: [../proposals/p4-derive-timbre.md](../proposals/p4-derive-timbre.md)

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P4-1 | Extend `VoiceTransformer` with `timbre(source, target, out)`, keeping `pitch` | `application/ports.py` | Existing derive tests still pass | S |
| P4-2 | Download `tone-color-vc-f16.gguf` (65.6 MB) into `models/tone-color/` and record its SHA-256 | `models/` (gitignored) | `sha256sum` matches the HF blob; file plays through `ffprobe` | S |
| P4-3 | `AudiocppConverter` adapter: `--task vc --family tone_color_vc --audio --voice-ref` with the runtime env | `adapters/secondary/audiocpp_converter.py` | Fake runner asserts the exact command shape | M |
| P4-4 | `DeriveService.derive(..., timbre_from=slug)`; transform type `timbre`; recipe records both hashes | `application/derive_service.py` | Unit test: recipe has `timbre_from` and both `*_sha256` | S |
| P4-5 | CLI `--timbre <slug>` (mutually exclusive with `--pitch`) and API field | `cli.py`, `http.py` | `derive alex --pitch 2 --timbre x` is rejected with a clear message | S |
| P4-6 | Real run: `alex` → timbre of `narrador-terror`, registered and previewed | `tests/e2e/derive-timbre/` | Evidence folder with the source, the target and the derived preview | M |
| P4-7 | Docs: recipe fields, licence note, roadmap P4 marked done | `docs/` | Docs match behaviour | S |

## Risk to watch
22.05 kHz output is the lowest rate in the system. It is already normalised by
the assembler, but P4-6 must render a **mixed** dialogue (44.1k line + 22.05k
line) to prove it in practice, not only in the unit test.

## Definition of done
A derived voice keeps the source performance and the target timbre, previews
distinctly from both parents, and survives `voice-forge verify`.
