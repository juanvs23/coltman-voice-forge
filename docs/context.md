# Context — voice-forge

## Purpose

A local voice factory for narrated video. It does three things and refuses to
become a platform:

1. **Create** a voice from a text description (prompt → audio).
2. **Clone** any reference clip into the catalog (a generated voice is just
   another reference).
3. **Narrate** a script with per-line emotional direction, reusing catalog
   voices, and deliver a mastered file.

## Domain vocabulary

| Term | Meaning |
|---|---|
| **Voice** | An immutable catalog entry: a reference clip plus the recipe that produced it. Identified by `slug`. |
| **Derived voice** | A voice created by transforming another voice's reference. `origin: derived`, with `derived_from` in the recipe. The source is never modified. |
| **Timbre conversion** | A derived voice that keeps one clip's performance (timing, emphasis) and borrows the identity of a second catalog voice. Recipe `transform: "timbre"` with `timbre_from` and both `*_sha256`; a second, separate port (`TimbreTransformer`), not a pitch shift. |
| **Recipe** | The provenance of a voice: brief, language, seed, model, picked candidate. Without it a voice cannot be reproduced. |
| **Brief** | The text description the operator writes to create a voice. |
| **Candidate** | One generated voice that is not yet registered. |
| **Emotion** | Eight normalised axes (`happy, angry, sad, afraid, disgusted, melancholic, surprised, calm`), a global `intensity`, and an optional free-text `hint`. |
| **Dialogue** | An ordered list of lines; each line names a voice and either `text` (synthesised, with emotion and speed) or `source` (an acted take). `base_dir` is the folder a relative `source` resolves against. |
| **Acted line** | A line with `source:` instead of `text`: a recorded take whose performance is converted to that line's voice with the timbre converter. `emotion` and `speed` are ignored (the take already carries the interpretation); `pause_after_ms` still applies. A relative `source` resolves against the dialogue's `base_dir` — the script's folder when loaded from disk, the server's working directory when the script arrives as API text. |
| **Chapter** | One named group of a long dialogue, written as `## chapter: name` in the script and rendered to its own file. The marker is a YAML comment, so the split happens on the raw text before YAML parsing; text before the first marker is the header and may only set `title`. |
| **Engine host** | The process that owns the model: the `audio.cpp` server by default; the optional Python host (`engines/qwen_host.py`) used only by the `qwen` adapter. |
| **Runtime** | The compiled C++ binary that executes GGUF models (`audiocpp_cli` / `audiocpp_server`). Lives in `dist/`; `voice-forge runtime build` produces it and records the decision in `dist/BUILD.json`. |
| **Warm** | Load weights and run a canary generation, so the first real line is not the slow one. |

## Structure

```
domain/       pure entities and rules; no I/O, no model names
application/  ports (contracts) + use cases (catalog, dialogue, derive)
adapters/
  primary/    CLI, HTTP API, Gradio console at /ui (webui/), MCP server (mcp/)
  secondary/  catalog on disk, engine HTTP client, engine supervisor, ffmpeg,
              pitch transform, timbre conversion (tone-color-vc)
engines/      qwen_host.py (optional adapter host; not the default path)
dist/         compiled runtime + BUILD.json (gitignored)
```

The console (`adapters/primary/webui/`) is a **client of the API**, not a second
backend: its pure handlers call the same services the endpoints call, and every
capability it shows has a REST resource (`/api/voices`, `/api/previews`,
`/api/voices/design/candidates`, `/api/voices/design/register`,
`/api/dialogues/render`, `/api/engine`, `/api/queue`). Gradio is imported only
inside that package; `gr.mount_gradio_app` keeps one process and one port.
`GET /` redirects to `/ui/`.

The CLI covers the same design flow, not just the one-call shortcut: `design`
auditions and registers in one step, while `audition` writes the candidates to
`out/candidates/` (through the same `AuditionStore`, behind the same serial
queue) and `register-candidate` quotes the printed token to register one. A
voice produced either way writes the same `voice.json`, so the CLI keeps parity
with the API and the console.

The MCP server (`adapters/primary/mcp/`) exposes the same capabilities as tools
for an agent in another project, and it is a **client of the API**, not a second
engine: every tool is an HTTP call to the running `serve`, so agent work enters
the same `SerialQueue`. `voice-forge serve` must be running; without it each tool
fails with a message naming the command. There is deliberately no delete tool —
removal stays with the operator.

## Invariants

- The domain never learns which model speaks. A model name in `domain/` is a bug.
- A voice is immutable. Changing one means a new slug; that keeps old renders
  reproducible. A bare name never follows a correction: versioning, if it is
  ever needed, is an explicit `narrador@2` address, not an implicit latest.
- The reference clip is the voice. Delete `ref.wav` and the voice is gone.
- The engine is optional at import time: the API and CLI start even with the
  engine down, and fail only when a model is actually needed.
- **One instance, one job.** Starting a second host is an error; extra work
  waits in a FIFO instead of running in parallel. The queue announces the active
  job in `out/active-job.*` (a held `flock` plus an atomic json), so `down` and
  `queue` see it from any process, not just the one that started it.
- **No kill without proof of ownership.** `down` requires the boot token stored
  in the pid file and signals through a pidfd; a recycled pid it cannot prove is
  its own is left alone.
- **Apache-2.0 / MIT only.** Custom-licensed weights are out of scope.

## Ownership

The repository is the **tool**; the catalog is the **instance's data**.

| The tool owns | The operator owns |
|---|---|
| The `voice.json` schema and directory layout | The voices themselves |
| Reading, validating, verifying integrity | Backups, retention, deletion |
| `out/`, `dist/`, code, docs | `catalog/` and where it lives |

Consequences that are deliberate, not oversights:

- `catalog/` is gitignored and no catalog is ever shipped with the repo.
- The path is configurable (`VOICEFORGE_CATALOG`); it belongs to the instance,
  not to the installation.
- There is **no** backup, restore, migrate, prune or "catalog manager" command.
  If an operator wants a backup, it is their `tar` and their cron.
- `voice-forge verify` is read-only: it reports, it never repairs or moves
  anything.

## Environment

- Host: RTX 4060 Laptop, 7.67 GB VRAM. **One model loaded at a time**; the host
  unloads the other mode before loading a new one.
- Core venv: created by `uv sync`, **no torch**.
- Runtime: `dist/bin/audiocpp_server` (and `audiocpp_cli`), built with
  `uv run voice-forge runtime build`. The CUDA backend links against a local
  cuFFT prefix unpacked under `dist/cuda/`, which the builder detects and
  records in `dist/BUILD.json`.
- Weights: `models/ming3/*.gguf` (Ming-3.0-TTS-0.5B, MIT) for speech and voice
  design; `models/tone-color-vc/tone-color-vc-f16.gguf` (tone-color-vc,
  OpenVoiceV2, **MIT**, 63 MB) for timbre conversion. Both trees are gitignored;
  the VC path is overridable with `VOICEFORGE_TIMBRE_MODEL`.
- Alternative adapter only: the model venv at `/path/to/qwen-tts/.venv`
  (torch + `qwen_tts`), used when `VOICEFORGE_ADAPTER=qwen`.
- Shared weights cache: `/path/to/huggingface-cache` (`HF_HOME`).
- `ffmpeg` and `ffprobe` from the system.
