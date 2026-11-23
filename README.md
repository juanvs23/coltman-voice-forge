# voice-forge

Local-first voice factory. Design a voice from a text prompt, clone it from
any reference clip, and narrate scripts with graded emotional direction —
all on your own GPU, with a CLI, an HTTP API and an operator console.

The core is hexagonal: the domain does not know which model speaks. Swapping
Ming-3.0-TTS for ZONOS3 or anything else is an adapter change, not a rewrite.

Two rules are enforced by the code, not by convention: **one instance only**
(a second `up` fails, the host holds an OS lock) and **one job at a time**
(every model call goes through a FIFO; extra requests wait in order).

Everything is **Apache-2.0 / MIT**: custom-licensed weights are out of scope.

## Why this exists

The workflow that actually produces good narration is:

1. **Design** the voice once from a description (`Ming-3.0-TTS` VoiceDesign
   over `audio.cpp`).
2. **Register** the resulting clip as a catalog voice — the same path an
   imported/third-party clip takes.
3. **Narrate** any number of lines with emotional direction, reusing the same
   reference for every sentence.

A voice is created once and used a thousand times. The catalog stores the
*recipe* (prompt, seed, model) next to the clip, so a voice is reproducible.

## Quick start

```bash
uv sync --extra dev

uv run voice-forge up          # start the model host
uv run voice-forge warm        # load weights + canary synthesis

# One shot: design and register in a single call.
uv run voice-forge design "hombre de 60, voz grave y rasposa, susurrante, español neutro" \
    --slug narrador-terror --candidates 4

# Or audition first: listen to the candidates, then register the one you pick.
uv run voice-forge audition "narrador grave y pausado" --candidates 4
#   token: 4b91daa3596b
#     0  /…/out/candidates/4b91daa3596b-0.wav  44100 Hz  instruct=narrador grave y pausado
#     ...
uv run voice-forge register-candidate 4b91daa3596b --pick 1 --slug narrador-pausado

uv run voice-forge voices
uv run voice-forge queue        # what is running and what is waiting

# Modify a voice: shift it, or borrow another voice's timbre.
uv run voice-forge derive narrador-terror --pitch -2 --slug narrador-mas-grave
uv run voice-forge derive alex --timbre narrador-terror --slug alex-hibrido

uv run voice-forge render examples/dialogo.yaml --out out/demo.wav
uv run voice-forge render examples/guion-3-capitulos.yaml --out out/narracion.wav --chapter
#   01  out/narracion-01.wav  6.0s  -14.9 LUFS  2 lines  la casa vacía
#   02  out/narracion-02.wav  5.0s  -13.8 LUFS  2 lines  la luz del pasillo
#   ...
# Mix your own acted performance with synthesised lines in one script.
uv run voice-forge render examples/guion-mixto.yaml --out out/mixto.wav
uv run voice-forge down
```

`--chapter` splits the script on `## chapter: name` lines and writes
`out/narracion-01.wav`, `-02.wav`… Each chapter is mastered at `--lufs`
(default −14) on its own and **measured** afterwards, so the report shows what
the file actually is. Without the flag the script is still one file.

A line carries `text:` to be synthesised, or `source:` to be **acted**: the
recording is converted to the line's voice and keeps its own performance
(`emotion`/`speed` are ignored there). One script can mix both:

```yaml
lines:
  - voice: narrador-terror
    text: "La puerta se abrió sola."
    emotion: { afraid: 0.6 }
  - voice: narrador-terror
    source: ../catalog/alex/ref.wav   # converted, timing preserved
```

A relative `source` resolves against the script's folder; a script sent as text
through the API resolves it against the server's working directory.

`design` is the fast path when the description is already trusted; `audition` +
`register-candidate` is the path when the take matters — the candidates stay in
`out/candidates/` until you register one, and only one audition is live at a
time (a new one replaces the files of the previous one).

Console and OpenAPI: `uv run voice-forge serve` → http://127.0.0.1:8720/ui
(API docs at http://127.0.0.1:8720/docs; `GET /` redirects to the console).
The console opens on the essentials — voice cards, an emotion preset, a render
button — and keeps per-axis control, derive and remove one click away. Narrate
is a line builder by default: add rows, pick a voice and write the text; the raw
YAML editor stays under *Advanced* for chapters and acted lines.

## Use it from another agent (MCP)

`voice-forge mcp` serves the catalog as **MCP tools** over stdio, so an agent in
another project can list voices, audition them, render scripts and create voices
without the CLI. It is a client of the running API, so all model work still goes
through the one serial queue — **start `serve` first**.

```json
{
  "mcpServers": {
    "voice-forge": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/voice-forge",
        "voice-forge",
        "mcp"
      ]
    }
  }
}
```

Twelve tools (`list_voices`, `preview_voice`, `render_dialogue`,
`design_candidates`, `register_candidate`, `clone_voice`, `derive_voice`,
`engine_status`, …) and deliberately no `remove_voice`. Setup for OpenCode, the
full tool table and the limits: [`docs/mcp.md`](docs/mcp.md).

## Requirements

- Python ≥ 3.12 (`uv` recommended).
- `ffmpeg` in `PATH`.
- The compiled runtime in `dist/bin` (`audiocpp_cli` / `audiocpp_server`), built
  with `uv run voice-forge runtime build`. The builder detects a CUDA toolkit
  under `dist/cuda/usr` and links against it; on this machine the binaries
  report `backends: cpu,cuda`.
- The weights: a Ming-3.0 GGUF under `models/ming3/`.
- For `derive --timbre`: the `tone-color-vc-f16.gguf` conversion model under
  `models/tone-color-vc/` (MIT, 63 MB; override with `VOICEFORGE_TIMBRE_MODEL`).
  Pitch-only `derive` does not need it.
- Only for the alternative `qwen` adapter (`VOICEFORGE_ADAPTER=qwen`): the
  `qwen-tts` virtualenv with torch and `qwen_tts`. Point elsewhere with
  `VOICEFORGE_ENGINE_PYTHON`.

The core environment has **no torch**. That is deliberate: a 200 MB install
must not become a 9 GB one.

## Project layout

```
src/voiceforge/
├── domain/          entities and rules (pure Python)
├── application/     ports + use cases
├── adapters/
│   ├── primary/     CLI, HTTP API, Gradio console (webui/)
│   └── secondary/   catalog on disk, engine HTTP client, ffmpeg assembler
├── config.py        settings from environment
└── container.py     wiring
engines/qwen_host.py model host (optional qwen adapter)
```

Docs: [`docs/context.md`](docs/context.md) ·
[`docs/architecture.md`](docs/architecture.md) ·
[`docs/roadmap.md`](docs/roadmap.md)

## License

The code is **Apache-2.0** (see [`LICENSE`](LICENSE)). The models keep their own
licenses — Ming-3.0 and tone-color-vc are MIT — and the catalog records which
model produced each voice, so provenance is never lost. Your voices are yours:
the catalog is operator data, never part of this repository.
