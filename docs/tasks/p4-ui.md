# P4 — Operator console: task breakdown

Spec: [../proposals/p4-ui.md](../proposals/p4-ui.md) · Stack: Gradio 6.32.0
mounted at `/ui`, REST API unchanged.

**Status: done (2026-11-23).** Every task below passed its own check; the
evidence per task is recorded in [Result](#result-2026-11-23).

Ordered. Each task is independently verifiable; a task is done when its check
passes, not when the code compiles.

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P4-1 | Pin `gradio` and mount an empty app at `/ui`, keeping `/api/*` untouched | `pyproject.toml`, `adapters/primary/http.py` | `GET /ui` → 200; `uv run pytest` still green | S |
| P4-2 | Gradio context object holding catalog, queue, engine, preview, derive (no globals) | `adapters/primary/webui/context.py` | Page renders the voice count from the real catalog | S |
| P4-3 | **Voices** screen: cards as `gr.HTML` from the catalog, with origin badge and `derived_from` | `webui/voices.py` | A designed, an imported and a derived voice all render distinctly | M |
| P4-4 | Voice actions: preview, derive, remove — all through `SerialQueue` | `webui/voices.py` | Actions work with the engine down (they fail with a readable message, never a traceback) | M |
| P4-5 | **Preview** screen: text, emotion, intensity, speed, `gr.Audio` output + microphone input | `webui/preview.py` | Three takes rotate through `slot-0..2`; the fourth overwrites the oldest | M |
| P4-6 | **Design** screen: prompt, candidate count, candidates side by side, pick and register | `webui/design.py` | Registering stores the recipe; an emotional prompt shows the neutral rule inline | M |
| P4-7 | **Narrate** screen: script textarea, YAML validation, render, queue progress | `webui/narrate.py` | A two-line script renders and the queue state is visible while it runs | M |
| P4-8 | **Engine** screen: status, up, warm, down, queue depth, device | `webui/engine.py` | `up` on a live server shows the 409 reason, not a crash | S |
| P4-9 | Delete the legacy vanilla page and its route | `adapters/primary/ui.py`, `http.py` | `GET /` redirects to `/ui`; no dead template left | S |
| P4-10 | `GET /api/previews` returning the three slots + sidecars | `http.py` | Returns 3 entries with voice, text, axes | S |
| P4-11 | Docs: screenshots or screen list in README; proposal marked done | `README.md`, `docs/proposals/p4-ui.md` | Docs match the shipped screens | S |

## Guardrails for this phase
- **The queue is ours.** Gradio's queue must never replace `SerialQueue`; the UI
  displays our state, it does not schedule work.
- No new endpoint may exist only for the UI: if a screen needs data, it is an API
  resource first and a Gradio call second.

## Definition of done
Design, compare, register and preview a voice without a terminal; render a script
watching the queue; every screen degrades honestly with the engine down.

## Result (2026-11-23)

| # | Check | Outcome |
|---|---|---|
| P4-1 | `GET /ui` → 200; `uv run pytest` still green | ✅ passed — `gradio==6.32.0` pinned; the console mounts with `gr.mount_gradio_app`; `GET /ui` 200 and `GET /ui/` 200; 226 tests pass |
| P4-2 | Page renders the voice count from the real catalog | ✅ passed — `UiContext.from_container` carries catalog, queue, engine, preview, derive, dialogue and settings, no globals; the header renders the live count and languages |
| P4-3 | A designed, an imported and a derived voice all render distinctly | ✅ passed — `cards_html` emits one card per voice with `origin` badge and `derived_from`; covered by `tests/unit/test_webui_voices.py` |
| P4-4 | Actions work with the engine down — readable message, never a traceback | ✅ passed — derive/remove/ready checks return operator sentences; `tests/unit/test_webui_voices.py` and `test_webui_preview.py` assert the message and the absence of `Traceback` |
| P4-5 | Three takes rotate through `slot-0..2`; the fourth overwrites the oldest | ✅ passed — `test_webui_preview.py::test_four_takes_leave_exactly_three_slots`; the console reads the same sidecars as `GET /api/previews` |
| P4-6 | Registering stores the recipe; an emotional prompt shows the neutral rule inline | ✅ passed — `tests/unit/test_webui_design.py` proves the registered `voice.json` matches the one-call API path and the neutral message names the triggering word |
| P4-7 | A two-line script renders and the queue state is visible while it runs | ✅ passed — `tests/unit/test_webui_narrate.py` blocks a synthesizer on a `threading.Event` and asserts an intermediate yield contains `busy`/`running` before the final path+duration yield; `GET /ui/config` carries `Narrate`, `Render`, `Validate` |
| P4-8 | `up` on a live server shows the 409 reason, not a crash | ✅ passed — `run_action` maps `EngineAlreadyRunning`, `EngineBusy` and `EngineUnavailable` to operator sentences; `tests/unit/test_webui_engine.py` |
| P4-9 | `GET /` redirects to `/ui`; no dead template left | ✅ passed — `ui.py` deleted; `GET /` → **308** with `location: /ui/` (`test_api.py::test_ui_is_served`, `test_console.py::test_root_redirects_to_the_console`); `/ui` 200 and `/ui/` 200 |
| P4-10 | Returns 3 entries with voice, text, axes | ✅ passed — `test_console.py` covers three empty slots, two sidecars with a gap, and a corrupt sidecar degrading to empty |
| P4-11 | Docs match the shipped screens | ✅ passed — README, `context.md`, proposal, this task list, changelog `0.15.0`, `AGENTS.md` and the odd task sheet describe the console at `/ui` |

## Definition of done (verified)
Live check on port 8793 with a temporary catalog: `GET /` → 308 to `/ui/`
without following the redirect, `GET /ui` → 200, `GET /ui/` → 200,
`GET /ui/config` → 200 and contains `Narrate`, `Render` and `Validate`, and
`GET /ui/assets/index-*.js` → 200 (`application/javascript`, 139 KB). The server
was stopped by pid; the temporary catalog was removed. No engine was needed for
this check.
