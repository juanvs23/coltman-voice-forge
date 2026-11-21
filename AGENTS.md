# AGENTS.md

> Project instructions for every coding agent working in this repository.
> Bootstrap copy of this kit's `project-agents-template.md`
> (development rule 8).

## Read first
- `docs/context.md` — purpose, structure, domain vocabulary
- `docs/roadmap.md` — phases and the next step
- `docs/architecture.md` — the hexagonal contract (why the core never imports a model)
- `docs/proposals/` — one spec per roadmap phase, with rejected alternatives
- `docs/tasks/` — the task list per phase, each with its own check

## Project rules
1. **Docs must not lie.** When behavior changes, update `docs/context.md` and
   `docs/roadmap.md` in the same work unit as the code that changed them.
   Preserve each doc's declared structure; restructure only when explicitly
   asked.
2. **Changelog.** Record user-facing changes in `docs/changelog.md` (Keep a
   Changelog format) as part of each work unit.
3. **Debt contracts.** Every `[DEBT]` marker needs a contract scheduled in
   `docs/roadmap.md` (global rule 7). No contract, no shortcut.
4. **Ignore file is law.** Never commit secrets, `.env`, local databases,
   caches (`__pycache__`, `.venv`), or rendered audio (`out/`, `catalog/*/`).
5. **Conventional commits.** No AI attribution lines.
6. **E2E evidence layout (shared rule 11).** Integration/E2E/exploratory
   runs and their evidence live in `tests/<type>/<name>/`: committed
   `README.md` + support code, gitignored `evidence/`. Never `/tmp`, never
   outside the repo.
7. **Language policy (shared rule 15).** Canonical artifacts in English:
   code, comments, configs, prompts, catalogs, canonical docs. Operator
   conversation and support reports stay in Spanish. Voice `instruct`
   strings and narration product content stay in the language they produce
   (Spanish).

## The dependency rule (non-negotiable)
`domain/` imports nothing from this project except itself and the stdlib.
`application/` imports `domain/` only (plus stdlib). `adapters/` may import
anything. A model name appearing inside `domain/` or `application/` is a bug.

## Licensing policy (non-negotiable)
The whole stack is **Apache-2.0 / MIT only**. Models under custom licenses
(bilibili's IndexTTS, CC-BY-NC, OpenRAIL, research-only weights) are out of
bounds, regardless of quality. Before adding a model, check the license field
on its model card and record it in `docs/roadmap.md`.

## Neutral reference (non-negotiable)
A catalog voice is a **neutral identity**; emotion belongs to each line. The
rule governs what gets **stored**, not what you may hear: previewing a voice with
an emotion is expected and never modifies the catalog. The system enforces it: `design` and `add` refuse a description whose instruct
carries emotion words (Spanish stems + English whole words), and the operator
must pass `--emotional` / `"emotional": true` to accept a non-neutral
reference. Delivery words ("susurrante", "ritmo lento") are style, not emotion,
and are allowed.

## Admission control (non-negotiable)
- Exactly **one** model host instance. `up` on a live host must fail, never
  spawn a second process; the host itself holds an OS lock as the backstop.
- Exactly **one** job at a time. Model work goes through `SerialQueue`; extra
  requests wait in FIFO order instead of competing for the GPU.
- `down` refuses while a job is running (`--force` to discard).

## Commands
```bash
uv sync --extra dev                 # core env (no torch)
uv run pytest -q                    # unit + integration (no GPU, no models)
uv run voice-forge status           # engine host health
uv run voice-forge queue            # depth and recent jobs
uv run voice-forge runtime plan     # detect GPU/toolchain and show the chosen backend
uv run voice-forge runtime build    # compile the model runtime into dist/ (CUDA, else Vulkan)
uv run voice-forge runtime status   # what was built, with backend and revision
uv run voice-forge verify           # prove every voice is still its original clip
# adapter selection: VOICEFORGE_ADAPTER=audiocpp|qwen  ·  VOICEFORGE_DEVICE=cpu|cuda|vulkan
uv run voice-forge up && uv run voice-forge warm
uv run voice-forge design "descripción de la voz" --slug mi-voz
uv run voice-forge add mi-clon.wav --slug mi-clon --name "Mi clon"
uv run voice-forge voices
uv run voice-forge render guion.yaml --out out/narracion.wav
uv run voice-forge serve            # API + web UI on :8720
uv run voice-forge down [--force]   # refuses while a job runs
```
The engine host runs inside the model venv:
`/path/to/qwen-tts/.venv/bin/python engines/qwen_host.py`
(override with `VOICEFORGE_ENGINE_PYTHON`).

## Guardrails
- Never import `torch`, `qwen_tts` or any model SDK inside `src/voiceforge/`.
  Models talk to the core only over HTTP through `adapters/secondary/engine_http.py`.
- Never write rendered audio or catalog entries into git.
- **`catalog/` is user data, not repository state.** The tool defines the
  contract (directory layout, `voice.json` schema, integrity check); the
  operator owns the bytes. Never ship a catalog, never commit one, and never
  add features that back up, migrate, prune, relocate or "manage" it. If the
  operator wants backups, that is their cron, their rsync, their decision.
- Never edit `catalog/<slug>/ref.wav` in place: a voice is immutable once
  registered; create a new slug instead.
- `out/` and `catalog/` are runtime state. Deleting them must never break
  the app (it recreates them) — but the tool never deletes a catalog itself.
