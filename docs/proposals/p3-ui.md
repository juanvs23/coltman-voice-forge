# P3 — Operator console (web UI)

## Goal
Make the system usable without a terminal for the four things an operator does:
keep the catalog, audition voices, design new ones, and narrate a script.

## Shape
A React client served by the FastAPI app that already exists.

```
GET /            -> HTML shell (one file, ~60 lines)
GET /static/*    -> react, react-dom, htm, app.js  (vendored, committed)
GET /api/*       -> the existing endpoints, unchanged
```

## Stack decision

| Option | Verdict |
|---|---|
| **React 18 UMD + htm, vendored** | ✅ chosen. No build step, no CDN, no Node. `react.production.min.js` + `react-dom.production.min.js` + `htm` total ~150 KB committed into `src/voiceforge/adapters/primary/static/`. Components are tagged template literals, which is JSX without a compiler |
| Gradio | ❌ rejected. It drags a large dependency tree into a core venv whose whole point is being light, imposes its own layout, and couples the UI to its runtime version. It also cannot express the catalog cards and the queue state without fighting the framework |
| Vite + React + TS | ❌ rejected. A build step and Node toolchain for a local tool is a worse tool: `git clone && uv sync` must be enough |
| Vanilla JS (today) | ⏸ kept as fallback until the console reaches parity, then deleted |
| Server-side rendering | ❌ rejected. React SSR needs Node; the server is Python |

If `react-dom` (≈130 KB) ever feels heavy, **Preact + htm** is a drop-in
alternative at ~12 KB with the same no-build model. That swap is one file.

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
- `GET /api/previews` — the three slots with their `slot-N.json` metadata.
- Nothing else: every screen maps to endpoints that already exist.

## Acceptance
- Design, compare, register and preview a voice **without opening a terminal**.
- Render a two-line script from the console and watch the queue state.
- With the engine down, every screen says so and offers `up`.
- No UI action exists that the API cannot do.

## Risks
- Vendored React ages: pin the version and record it in this document when it
  changes. It is a static asset, not a dependency to resolve.
- Two UIs during the transition (vanilla + console). Delete the old page the day
  parity is reached, not later.
