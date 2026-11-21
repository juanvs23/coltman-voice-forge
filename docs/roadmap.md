# Roadmap

> Structure contract: Next step pinned at top, phases with status
> (done/current/next), acceptance criteria per phase, then the backlog and the
> debt schedule. Update the Next Step on every completed work unit.

## Next step
**P3 — Operator console (UI).** Everything below works from the CLI; the console
is what makes it a tool instead of a pipeline. Start with the catalog + preview
screens, which cover 90 % of daily use.

## Snapshot (2026-11-20)

| Thing | State |
|---|---|
| Create a voice from a prompt | ✅ `vdes`, catalog, recipe |
| Clone a voice from any clip | ✅ zero-shot, human clip verified |
| Narrate with graded emotion | ✅ freeform instruction from the eight axes |
| Modify a voice into a new one | ✅ `derive` (pitch/formants, no model) |
| Speed | ✅ 2.5 s for a two-line render (CUDA, resident server) |
| Interfaces | CLI complete · REST API · minimal single-page UI |
| Tests | 93, no GPU or models required |
| Licences | Apache-2.0 / MIT across runtime, models and dependencies |
| Disk | `dist/` 11 GB (9.7 GB rebuildable) · model 1.7 GB · catalog is user data |

## Principles (do not renegotiate per feature)

1. **The core owns nothing external.** `domain/` and `application/` never name a
   model, an HTTP client or a process. Adapters are replaceable by design.
2. **Apache-2.0 / MIT only.** Custom, copyleft and research-only weights are out,
   regardless of quality.
3. **One instance, one job.** A second `up` fails; work queues in FIFO.
4. **A voice is a neutral identity.** Emotion belongs to each line. The rule
   gates storage, never audition.
5. **The catalog belongs to the operator.** The tool defines the contract; it
   never backs up, migrates, prunes or relocates a catalog.
6. **Consent is the operator's responsibility.** No consent fields, no DRM, no
   policing of imported voices. Documented, not implemented.

## Phases

### P1 — Skeleton that runs — done
Hexagonal layout, five ports, filesystem catalog with recipe and guide, dialogue
service, ffmpeg assembler, CLI, REST API, tests with fakes.

### P2 — Emotion that lands — done
Ming-3.0-TTS-0.5B GGUF (MIT) over audio.cpp. Adapter composes the eight axes into
one Spanish instruction; operator confirmed the emotion is audible.

| Fact | Value |
|---|---|
| Licence | MIT · languages zh, en, ja, ko, de, fr, **es** |
| Size | Q8_0 1.7 GB · bf16 3.0 GB |
| VRAM | 1.9 GB (Q8) |
| Runtime | `audiocpp_cli` / `audiocpp_server`, CUDA build from a local cuFFT prefix |
| Tasks | `tts`, `clon`, `vdes` |

Known limit: no numeric intensity dial — intensity is expressed in words.

### P3 — Operator console (UI) — next

> Spec: [proposals/p3-ui.md](proposals/p3-ui.md)

Today's UI is one page: catalog table, design form, add form, render textarea and
a preview panel. It proves the API and nothing more. The console replaces it with
the four things an operator actually does, in one screen each.

**Scope**
1. **Voices** — cards instead of a table: name, slug, origin badge
   (`designed` / `imported` / `derived`), language, rate, recipe summary,
   `derived_from` link when applicable, and the actions that belong to a voice
   (preview, derive, remove).
2. **Preview** — text, emotion selector, intensity and speed sliders, inline
   player, and a short history of the last takes so two emotions can be compared
   without leaving the page.
3. **Design** — prompt, candidate count, generated candidates played side by
   side, pick one and register it with its recipe; the neutral-reference rule
   surfaced inline instead of as a raw error.
4. **Narrate** — script editor with YAML validation, live cost estimate (lines ×
   rate), render button, and the queue state while it runs.
5. **Engine** — up / warm / down with real status, queue depth and the active
   device, so the lifecycle stops being a CLI secret.

**Constraints**
- No build step, no CDN, no framework: one static HTML + fetch, served by the
  existing FastAPI app. A local tool that needs `npm install` is a worse tool.
- Every screen degrades honestly when the engine is down: it says so and offers
  `up`.
- Errors from the domain (`ValidationError`, `EngineBusy`, `VoiceExists`) render
  as operator language, not stack traces.

**Acceptance**
- A new voice can be designed, compared, registered and previewed without
  opening a terminal.
- Render a two-line script from the console and see the queue state while it runs.
- No UI action exists that the API cannot do; the UI is a client, never a special
  path.

### P4 — Derive by timbre (voice conversion)

> Spec: [proposals/p4-derive-timbre.md](proposals/p4-derive-timbre.md)

Current `derive` shifts pitch and formants (0 MB, instant). The missing half is
moving a voice **toward another voice's timbre**.

| Item | Value |
|---|---|
| Model | `tone-color-vc-f16.gguf` (OpenVoiceV2) — MIT, 65.6 MB |
| Task | `--task vc --family tone_color_vc --audio <source> --voice-ref <target>` |
| Output | 22.05 kHz (the assembler already normalises mixed rates) |
| Code | one `VoiceTransformer` backend + `--timbre <slug>` |

```bash
voice-forge derive alex --timbre narrador-terror --slug alex-hibrido
```

Excluded: `seed_vc` (GPL-3.0), `vevo2` (CC-BY-NC-ND).

**Acceptance:** a derived voice keeps the source performance and the target
timbre, is registered with `derived_from` + both source hashes, and previews
distinctly from both parents.

### P5 — Long-form delivery

> Spec: [proposals/p5-longform.md](proposals/p5-longform.md)

- Chaptered output: one script → several files with per-scene loudness.
- A `source:` line type so a script can mix synthetic lines with the operator's
  own acted performances converted into a catalog voice.
- Voice versioning (`slug@2`) without breaking existing scripts.
- Optional duration guard: strong emotions measured ~25 % longer than neutral on
  one sentence; a ceiling would catch over-generation.

### P6 — Operational polish

> Spec: [proposals/p6-ops.md](proposals/p6-ops.md)

- Teach `RuntimeBuilder` the local cuFFT prefix (see debt).
- Kill the pid we started, not every process with the runtime's name.
- Prune decision for the `dist/` build trees.
- CI running `uv run pytest` on push.

## Backlog (unprioritised)

> Detail: [proposals/backlog.md](proposals/backlog.md)

- Per-voice `conditioning: speaker | icl` — waiting for a character that needs it.
- Bilingual scripts (one voice per language, same character).
- Speaker diarisation of an imported long recording, to cut references.
- Emotion library: named presets (`terror-susurro`, `cierre-amargo`) stored per
  project, so a script can reference `emotion: terror-susurro`.
- Loudness report per render (LUFS integrated, true peak) instead of blind trust.
- MCP server exposing the catalog as tools, for agent-driven narration.

## Debt schedule

| Marker | What was shortcut | Why | Resolve by |
|---|---|---|---|
| `[DEBT] builder-cuda-prefix` | `RuntimeBuilder` builds CPU-only; the CUDA build was done by hand against `dist/cuda` | The prefix + include flags were discovered mid-build and not folded back | Add prefix detection (`dist/cuda/usr/{lib64,include}`) and the two `-I` flags to the builder; test with a fake runner. Until then, **do not run `runtime build` on this machine** |
| `[DEBT] server-kill-by-name` | `down()` uses `pkill -x audiocpp_server` | Enough for a single-user box | Track the pid from `up()` and signal that pid group only |

## Decision log

| Date | Decision |
|---|---|
| 2026-11-20 | Apache/MIT only; IndexTTS excluded by licence |
| 2026-11-20 | One instance, one job: reject a second `up`, queue the rest |
| 2026-11-20 | Identity is the clip, not the prompt; `ref_sha256` + `verify` |
| 2026-11-20 | Catalog is user data; no backup/migrate/prune features |
| 2026-11-20 | Neutral reference enforced at storage, audition always allowed |
| 2026-11-20 | Consent is the operator's responsibility, not a field |
| 2026-11-20 | Speaker-only conditioning is the default; ICL stays unimplemented |
