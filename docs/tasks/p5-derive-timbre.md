# P5 — Derive by timbre: task breakdown

Spec: [../proposals/p5-derive-timbre.md](../proposals/p5-derive-timbre.md)

**Status: done (2026-11-23).** Every task below passed its own check; evidence
per task is in [Result](#result-2026-11-23).

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P5-1 | Add `TimbreTransformer` (`source, target_ref, out`), keeping `VoiceTransformer.pitch` | `application/ports.py` | Existing derive tests still pass | S |
| P5-2 | Download `tone-color-vc-f16.gguf` (63 MB) into `models/tone-color-vc/` and record its SHA-256 | `models/` (gitignored) | `sha256sum` matches the recorded digest; file loads through the runtime | S |
| P5-3 | `AudiocppTimbre` adapter: `--task vc --family tone_color_vc --audio --voice-ref` with the runtime env | `adapters/secondary/audiocpp_timbre.py` | Fake runner asserts the exact command shape | M |
| P5-4 | `DeriveService.derive(..., timbre_from=slug)`; transform type `timbre`; recipe records both hashes | `application/derive_service.py` | Unit test: recipe has `timbre_from`, `source_sha256` and `timbre_sha256` | S |
| P5-5 | CLI `--timbre <slug>` (mutually exclusive with `--pitch`) and API field | `cli.py`, `http.py` | `derive alex --pitch 2 --timbre x` is rejected with a clear message | S |
| P5-6 | Real run: `alex` → timbre of `narrador-terror`, registered and previewed | catalog + `out/previews` | Evidence: recipe, hashes, `verify`, duration/RMS/centroid | M |
| P5-7 | Queue the conversion like every other model job | `http.py`, `cli.py`, `webui/voices.py` | API history shows `kind: derive`; the job runs on the shared `SerialQueue` | S |
| P5-8 | Console: timbre dropdown beside the pitch slider, `timbre_from` in the recipe summary | `webui/app.py`, `webui/voices.py`, `webui/context.py` | A timbre derive from the console ignores the slider; card shows `timbre_from` | S |
| P5-9 | MCP `derive_voice(..., timbre=...)` sending timbre and no pitch | `mcp/tools.py`, `mcp/client.py`, `mcp/server.py` | Client body has `timbre` and no `pitch` | S |
| P5-10 | Docs: recipe fields, licence/location note, roadmap P5 done, changelog | `docs/`, `README.md`, `AGENTS.md`, `odd/tasks/` | Docs match behaviour | S |

## Risk to watch
22.05 kHz output is the lowest rate in the system, and the derived clip is also
a valid `ref.wav` for later synthesis. The assembler already normalises mixed
rates; P5-6 previews the 22.05 kHz voice through the TTS host to prove it in
practice, not only in the unit test.

## Definition of done
A derived voice keeps the source performance and the target timbre, previews
distinctly from both parents, and survives `voice-forge verify`.

## Result (2026-11-23)

| # | Check | Outcome |
|---|---|---|
| P5-1 | Existing derive tests still pass | ✅ `TimbreTransformer` added with `timbre()`; `VoiceTransformer.pitch()` untouched; `test_derive.py` unchanged and green |
| P5-2 | SHA-256 matches; valid GGUF | ✅ `models/tone-color-vc/tone-color-vc-f16.gguf`, 65,644,736 bytes, SHA-256 `7dcaff0888e2cdc3468a5a402287edb4f04c461e38a0e7ce69bf73a5c227fe70`; MIT `LICENSE` (MyShell.ai, 2024) alongside it; `models/` is gitignored |
| P5-3 | Fake runner asserts the exact command shape | ✅ `tests/unit/test_audiocpp_timbre.py`: binary, `--task vc`, `--family tone_color_vc`, `--backend cuda`, `--model`, `--audio`, `--voice-ref`, `--out`, timeout 42 s; non-zero exit and empty file both raise `RenderFailed` |
| P5-4 | Recipe has `timbre_from` and both hashes | ✅ `tests/unit/test_derive_timbre.py`: full recipe equality, `origin=derived`, 22,050 Hz, default name `Alex como Narrador terror`, source language and neutrality; the derived clip survives removing both parents |
| P5-5 | `--pitch` + `--timbre` rejected with a clear message | ✅ service raises `ValidationError("choose pitch or timbre, not both")`; API returns 400 (`test_derive_endpoint_rejects_pitch_and_timbre_together`); CLI surfaces it through `main()` exit 2 |
| P5-6 | Real run registered and previewed | ✅ `derive alex --timbre narrador-terror --slug alex-hibrido` exit 0 in **1.0 s**; `show` → 22,050 Hz, 10.170 s, recipe with both SHA-256; `verify` → `alex-hibrido ok`; previews with the same sentence: centroid **2,006 / 2,364 / 2,310 Hz** (alex / narrador-terror / hybrid) |
| P5-7 | API history shows `kind: derive`; the job runs on the shared `SerialQueue` | ✅ `test_derive_endpoint_accepts_a_timbre_and_quotes_no_pitch` asserts the last queue entry is `derive`; CLI uses `_queued(..., kind="derive")`, the console `ctx.queue.submit("derive", …)`, both waiting on the serial worker |
| P5-8 | Console timbre derive; card shows `timbre_from` | ✅ `tests/unit/test_webui_voices.py::test_derive_by_timbre_ignores_the_pitch_slider` (pitch -6 is ignored, recipe has no `pitch_semitones`, card carries `timbre_from=target-voice`); `RECIPE_KEYS` includes `timbre_from` |
| P5-9 | Client body has `timbre` and no `pitch` | ✅ `tests/unit/test_mcp_client.py::test_derive_voice_by_timbre_sends_the_timbre_and_no_pitch`; `tests/unit/test_mcp_tools.py::test_a_timbre_derive_sends_the_timbre_and_omits_the_pitch` |
| P5-10 | Docs match behaviour | ✅ roadmap P5 done with outcome, this table, proposal outcome, `context.md`, `architecture.md`, `README.md`, `AGENTS.md`, changelog `0.17.0`, `odd/tasks/voice-forge.md` |
