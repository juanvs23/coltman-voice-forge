# P4 — Operator console (web UI)

> Task breakdown: [tasks/p4-ui.md](../tasks/p4-ui.md)

**Status: implemented (2026-11-23).** Shipped at `/ui` on Gradio 6.32.0; the
legacy vanilla page is deleted and `GET /` redirects.

## Goal
Make the system usable without a terminal for the four things an operator does:
keep the catalog, audition voices, design new ones, and narrate a script.

## Shape
A Gradio 6.32.0 client mounted at `/ui` and served by the FastAPI app that
already exists. Gradio is a UI library, not a second server:
`gr.mount_gradio_app` keeps one process and one port.

```
GET /            -> 308 redirect to /ui/
GET /ui          -> 200 entry page with a meta-refresh to /ui/
GET /ui/         -> Gradio app, mounted with gr.mount_gradio_app
GET /api/*       -> the existing endpoints, unchanged
```

## Stack decision — reversed on measurement (2026-11-20)

First call was React UMD + `htm` vendored. The operator argued Gradio wins
because the dependency weight is cheaper than the development time. Measured
instead of argued:

| Measurement | Value |
|---|---|
| Core venv today | 32 MB |
| Venv with Gradio 6.32 | **253 MB** (+221 MB) |
| Packages added | 111 |
| Torch pulled in | **no** (the heavy ones are pandas 45 MB, numpy 30 MB, pillow 21 MB) |
| Install time (warm cache) | 3.2 s |
| Build step / Node / CDN | none — same as the React plan |

So the cost is real but bounded: 221 MB on a box with 336 GB free, no torch, no
toolchain. The operator's argument holds.

| Option | Verdict |
|---|---|
| **Gradio 6.32.0 mounted at `/ui`** | ✅ **chosen and shipped.** Free layout, forms, sliders, `gr.Audio` (player **and** microphone, which is what the act-it-yourself flow needs), progress and queue, and `gr.mount_gradio_app` keeps our FastAPI app as the single server |
| React 18 UMD + htm, vendored | ⏸ fallback if Gradio's layout fights the catalog cards. ~150 KB, no build |
| Vite + React + TS | ❌ build step and Node for a local tool |
| Vanilla JS (today) | ⏸ deleted the day the console reaches parity |
| Server-side rendering | ❌ needs Node; the server is Python |

**The accepted costs, written down so they are not surprises later:**
1. **Two queue concepts.** Gradio brings its own queue; ours (`SerialQueue`) is
   the real one. Gradio handlers must call our queue and *display* its state,
   never replace it. Otherwise the admission rule that protects the GPU dies in
   the UI layer.
2. **Styling is Gradio's.** Origin badges and voice cards need `gr.HTML` blocks
   rendered from our own data; we do not get pixel control.
3. **Version churn.** Gradio moves majors fast (pinned at 6.32.0). Pin it exactly
   and record the version here when it changes.

Unchanged: the UI is a client of the REST API — no Gradio-only path to the
catalog.

## Screens

### 1. Voices
Cards, not a table. Each card: name, slug, origin badge (`designed` /
`imported` / `derived`), language, sample rate, a recipe summary, a link to
`derived_from` when it exists, and the actions that belong to a voice:
**preview**, **derive**, **remove**.

### 2. Preview
Text field, emotion selector (neutral + the eight axes), intensity and speed
sliders, an inline player, and the last three takes visible as slots.

`out/previews/` holds exactly **three slots** (`slot-0..2.wav`) plus a
`slot-N.json` with the provenance of that take. A fourth preview overwrites the
oldest. The directory has a constant size by construction; no retention job, no
accumulation.

### 3. Design
Prompt, candidate count, the candidates played side by side, pick one, register.
The neutral-reference rule is shown inline (which word triggered it) instead of
surfacing a raw `ValidationError`.

### 4. Narrate
Script editor with YAML validation, a cost estimate (lines × measured rate),
render button, and the queue state (`busy`, `pending`, running job) while it
works.

### 5. Engine
`up` / `warm` / `down`, real status, queue depth, device and model. The lifecycle
stops being a CLI secret.

## API additions required
The console is a client, so every screen maps to an API resource. Three
resources and one static mount were added for P4:

- `GET /api/previews` — the three slots with their `slot-N.json` metadata.
- `POST /api/voices/design/candidates` — generate and audition candidates,
  writing `out/candidates/<token>-<n>.wav` plus a sidecar, and return the token
  and one entry per candidate. No catalog write.
- `POST /api/voices/design/register` — register one candidate by token and
  index; paths and recipes stay server-side.
- `GET /candidates/*` — static mount for the audition players (the previews
  mount already existed).

Everything else the screens use (`/api/voices`, `/api/voices/{slug}/preview`,
`/api/voices/{slug}/derive`, `/api/dialogues/render`, `/api/engine`,
`/api/queue`) predates P4.

## Acceptance
- Design, compare, register and preview a voice **without opening a terminal**.
- Render a two-line script from the console and watch the queue state.
- With the engine down, every screen says so and offers `up`.
- No UI action exists that the API cannot do.

## Risks
- **Resolved:** the two-UI transition (vanilla + console) ended with parity. The
  legacy page is deleted; `GET /` is a 308 to `/ui/`.
