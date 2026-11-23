# Roadmap

> Structure contract: Next step pinned at top, phases with status
> (done/current/next), acceptance criteria per phase, then the backlog and the
> debt schedule. Update the Next Step on every completed work unit.

## Next step
**P5 — Derive by timbre.** Current `derive` shifts pitch and formants; the
missing half is moving a voice toward another voice's timbre with a small MIT
model, registered as `derived_from` with both source hashes.

## Snapshot (2026-11-23)

| Thing | State |
|---|---|
| Create a voice from a prompt | ✅ `vdes`, catalog, recipe |
| Clone a voice from any clip | ✅ zero-shot, human clip verified |
| Narrate with graded emotion | ✅ freeform instruction from the eight axes |
| Modify a voice into a new one | ✅ `derive` (pitch/formants, no model) |
| Speed | ✅ 2.5 s of model work for a two-line render (CUDA, resident server, warm); 6.4 s end to end including CLI startup and assembly (2026-11-23) |
| Interfaces | CLI · REST API · Gradio console at `/ui` |
| Tests | 233, no GPU or models required |
| Licences | Apache-2.0 / MIT across runtime, models and dependencies |
| Disk | `dist/` 1.1 GB after pruning (runtime 476 MB + sources 369 MB); the object tree (~9.7 GB) is recreated on demand by `runtime build --force` · model 1.7 GB · catalog is user data |

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

### P3 — De-risk the silent failures — done

> Spec: [proposals/p3-derisk.md](proposals/p3-derisk.md) · Tasks: [tasks/p3-derisk.md](tasks/p3-derisk.md)

Four defects that produce no error message, closed before any new capability.

**Outcome (2026-11-23)**
- **The builder owns the CUDA prefix.** `voice-forge runtime build --backend cuda
  --force` ran unattended for ~21 min, exited 0 with `action: built`, and recorded
  the local prefix, the compiler, arch 89 and all eight flags in `dist/BUILD.json`.
  The resulting `audiocpp_cli` (99 MB) and `audiocpp_server` (107 MB) both report
  `backends: cpu,cuda`.
- **`down` is pid-scoped and ownership-verified.** `up` persists
  `{pid, port, token, started_at}` (atomic write) with a random token that it
  also injects as `VOICEFORGE_SERVER_TOKEN` into the server's environment.
  `down` opens a pidfd for the recorded pid, checks `/proc/<pid>/environ` for
  that exact token, and only then signals — through the same descriptor — TERM,
  `wait(15)`, KILL, `wait(5)`; the wait is a `select` on the pidfd, never
  `os.kill(pid, 0)`. A pidfd alone proves continuity, not ownership, so a pid
  recycled with a live owner fails the token check and is never touched; no
  token (legacy file) also means no signal. Without a token match and with the
  server still up, `down` raises `EngineUnavailable` and keeps the pid file; if
  the server is gone the file is removed as garbage. It refuses with
  `EngineBusy` while a job runs unless `--force`. The two-servers-one-killed case
  is proven by a unit test (it signals the pid in the file and nothing else), not
  by a live pair of servers.
  Also measured: `audio.cpp` has no `/shutdown` (404), and the old HTTP path
  waited out its five-second grace period after a refusal. `down` now only waits
  when the endpoint answers below 400, so a real stop went from **5.33 s to
  0.217 s** with `via: "signal"`.
- **The event loop stays free.** Blocking handlers are plain `def`, so Starlette
  runs them in its threadpool; `GET /api/queue` answers during a render.
- **Admission crosses processes.** `SerialQueue` announces the running job
  through a `JobState` port (`out/active-job.lock` held with `flock` for the
  whole job, `out/active-job.json` written atomically), so `down` in a second
  terminal sees it and exits 2 ("a job is running") instead of stopping the host
  under a live render; `voice-forge queue` from that terminal reports
  `busy: true` with `active: {kind: render, pid: 72528}`. A second concurrent job
  is refused with `EngineBusy`.

E2E after the rebuild: `up` → pid 41376 with `out/server.pid` written, `warm` 0.6 s,
`render examples/dialogo.yaml` → 6.4 s for 2 lines, `down` → `{"status":"down",
"pid":41376}` leaving no stale pid file. The cross-process run was separate: a
ten-line render in one terminal (exit 0, 32.0 s), `queue` and a refused `down`
(exit 2) from another, then `down` exit 0 with `out/server.pid` and
`out/active-job.json` removed. 114 tests pass.

### P4 — Operator console (UI) — done

> Spec: [proposals/p4-ui.md](proposals/p4-ui.md) · Tasks: [tasks/p4-ui.md](tasks/p4-ui.md)

Before P4 the UI was one page: catalog table, design form, add form, render
textarea and a preview panel. It proved the API and nothing more. The console
replaced it with the four things an operator actually does, one screen each.

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
- Gradio 6.32.0, pinned, mounted at `/ui` with `gr.mount_gradio_app`. No Node, no
  build step, no CDN; the FastAPI app stays the single server. `SerialQueue`
  remains the only scheduler — Gradio's own queue is display plumbing, never a
  second admission path. The pin is recorded in the proposal; the measured cost
  is +221 MB and no torch.
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

**Outcome (2026-11-23)**
- **Five screens on one process.** Gradio 6.32.0 is mounted at `/ui` with
  `gr.mount_gradio_app`: Voices (cards, derive, remove), Preview (text, the eight
  axes, intensity, speed, three rotating slots), Design (audition candidates,
  play them, register the chosen one), Narrate (YAML editor, validation and
  estimate, streamed queue progress, `gr.Audio` result) and Engine (up / warm /
  down, real status, queue depth). No Node, no build step, no CDN.
- **Audition never touches the catalog.** `POST /api/voices/design/candidates`
  writes the takes to `out/candidates/` and returns a token;
  `POST /api/voices/design/register` stores the chosen candidate through the same
  path as the one-call `POST /api/voices/design`, writing the same `voice.json`.
- **The console is the only page.** `GET /` answers **308** to `/ui/`; `GET /ui`
  answers **200** with a meta-refresh to `/ui/` so Gradio's relative assets stay
  correct; `GET /ui/` is the app. The legacy vanilla template (`ui.py`) is
  deleted.
- **`SerialQueue` is still the only planner.** Gradio's own queue is never
  started; render, design and preview handlers submit to ours and paint
  `busy`/`pending`.
- Tests: **226**, no GPU or models required. The Narrate progress test blocks a
  synthesizer on a `threading.Event` and asserts an intermediate yield carries
  `busy`/`running` before the final one.

### P5 — Derive by timbre (voice conversion)

> Spec: [proposals/p5-derive-timbre.md](proposals/p5-derive-timbre.md) · Tasks: [tasks/p5-derive-timbre.md](tasks/p5-derive-timbre.md)

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

### P6 — Long-form delivery

> Spec: [proposals/p6-longform.md](proposals/p6-longform.md) · Tasks: [tasks/p6-longform.md](tasks/p6-longform.md)

- Chaptered output: one script → several files with per-scene loudness.
- A `source:` line type so a script can mix synthetic lines with the operator's
  own acted performances converted into a catalog voice.
- Voice versioning (`slug@2`) without breaking existing scripts.
- Optional duration guard: strong emotions measured ~25 % longer than neutral on
  one sentence; a ceiling would catch over-generation.

### P7 — Operational polish

> Spec: [proposals/p7-ops.md](proposals/p7-ops.md) · Tasks: [tasks/p7-ops.md](tasks/p7-ops.md)

Give `dist/` pruning an explicit, auditable command: the build tree (~9.7 GB) is
recreated by `runtime build --force`, so it can go between builds and must never
be deleted by hand. The 2026-11-23 cleanup (`build`, the superseded `build-cuda`
tree and the downloaded rpms) was done manually and is what the command automates.
Also add CI so a regression cannot reach main unnoticed. The build and stop
defects moved to P3; preview retention was solved by the three-slot rotation.

## Backlog (unprioritised)

> Detail: [proposals/backlog.md](proposals/backlog.md)

- Per-voice `conditioning: speaker | icl` — waiting for a character that needs it.
- Bilingual scripts (one voice per language, same character).
- Speaker diarisation of an imported long recording, to cut references.
- Emotion library: named presets (`terror-susurro`, `cierre-amargo`) stored per
  project, so a script can reference `emotion: terror-susurro`.
- Loudness report per render (LUFS integrated, true peak) instead of blind trust.

## Debt schedule

No open debt contracts.

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
| 2026-11-23 | The builder owns the CUDA prefix; no hand builds, and `dist/BUILD.json` is the only record of how the binary was made |
| 2026-11-23 | `down` is pid-scoped — it signals the pid `up` recorded, never a process name — and refuses while a job runs |
| 2026-11-23 | Blocking endpoints are sync handlers, so Starlette's threadpool keeps the event loop free |
| 2026-11-23 | Admission state is a file, not IPC: `flock` on `out/active-job.lock` held for the job plus atomic `out/active-job.json`; the kernel releases the lock on a crash, so no daemon and no stale "busy" |
| 2026-11-23 | The CLI keeps parity with the API/UI for the design flow: `audition` writes the same `out/candidates` layout and `register-candidate` writes the same `voice.json`, instead of a CLI-only path |
| 2026-11-23 | Stopping the host needs two facts: **pidfd for continuity, boot token for ownership, no `killpg`**. A pid file is a hint; a pidfd alone cannot tell our server from a stranger that inherited the number |
| 2026-11-23 | MCP is a **client of the API**, not a second engine: `voice-forge mcp` speaks stdio and calls `serve` over HTTP, so agent work enters the same `SerialQueue` and the admission lock stays the truth. No delete tool: an autonomous agent must not remove the operator's voices |
