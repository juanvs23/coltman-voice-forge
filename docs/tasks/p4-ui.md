# P4 — Operator console: task breakdown

Spec: [../proposals/p4-ui.md](../proposals/p4-ui.md) · Stack: Gradio 6.x mounted
at `/ui`, REST API unchanged.

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
