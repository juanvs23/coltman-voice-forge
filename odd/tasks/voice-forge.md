# Feature: voice-forge — local voice catalog and narrator

## Objective
A local-first system with exactly three verbs — create a voice from a prompt,
clone a voice from any clip, narrate a dialogue with graded emotion — with an
API, a CLI, a practical UI and an explicit on/warm/use/off lifecycle.

## Why
VoiceStudio was 10 GB of platform paying rent for one or two occasional
functions, and its TTS engine (OmniVoice) could not steer emotion. The
operator needs an owned system whose core outlives whichever model is in
fashion.

## Scope (authorized)
- New repository `voice-forge` (greenfield, no migration of old audio).
- Hexagonal architecture; domain independent of models.
- Design-then-clone invariant: a generated voice enters the catalog through
  the same door as an imported clip.
- CLI + REST API + single-file UI.
- ffmpeg assembly with optional LUFS mastering.

Out of scope: audio translation (removed at the operator's request), ASR,
video generation.

## Constraints
- GPU: RTX 4060 Laptop, 7.67 GB VRAM → one model loaded at a time.
- Core venv must not contain torch.
- Canonical artifacts in English; operator conversation in Spanish.

## Tasks
| # | Task | Route | Evidence |
|---|---|---|---|
| 1 | Domain entities and rules | inline (fully specified, no research) | `tests/unit/test_domain.py` |
| 2 | Ports and use cases | inline | `tests/unit/test_catalog.py`, `test_dialogue.py` |
| 3 | Filesystem catalog adapter | inline | 6 tests incl. atomic staging |
| 4 | Engine HTTP client + supervisor | inline | exercised by API tests with fakes |
| 5 | ffmpeg assembler | inline | real ffmpeg run (`tests/integration/test_ffmpeg_assembler.py`) |
| 6 | CLI + API + UI | inline | API contract tests |
| 7 | Model host (qwen) | inline | manual `up`/`warm` next step |
| 8 | Docs, AGENTS, roadmap | inline | this folder |

**Route declaration:** inline was chosen deliberately. The design was fully
resolved before the first write (ports, contracts, file layout), the work is
mechanical once specified, and inter-file coherence dominated the handoff
cost of a writer sub-agent. No exploration trigger fired: the model APIs were
already read from the installed package.

## Acceptance criteria
- [x] `uv run pytest -q` green without GPU or models.
- [x] `grep -E "qwen|torch|indextts" src/voiceforge/{domain,application}` empty.
- [x] CLI lists, designs, registers and renders through the same ports.
- [x] A voice created by prompt is indistinguishable downstream from an
      imported clip.
- [ ] First real render with the engine host (next step).

## Known gap
Qwen3-TTS Base clones but ignores emotion instructions → `/health` reports
`emotion: unsupported-by-speech-backend`. Roadmap P2 (IndexTTS or ZONOS3
adapter behind the same port).

## Next step
`up` → `warm` → `design` → `render examples/dialogo.yaml`.
