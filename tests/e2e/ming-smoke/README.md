# E2E — Ming-3.0 smoke run (first Spanish synthesis)

Run: 2026-11-20 · commit `a282e4e` of audio.cpp · backend **CPU** ·
model `ming-3.0-tts-0.5b-q8_0.gguf` (1.74 GB, MIT).

## Why this run exists

Before writing the adapter we needed proof of three things: the compiled
runtime executes a GGUF, Ming speaks Spanish, and the emotion controls actually
change the audio. All three were confirmed here. The audio lives in
`evidence/` (gitignored, per the shared E2E rule).

## Files

Listen in this order — it answers three different questions.

**A. Do the Spanish labels move the voice?**
| File | Label | Duration | Peak |
|---|---|---|---|
| `02-emotion-neutral.wav` | `中性` | 2.40 s | −1.4 dB |
| `09-es-sad.wav` | `悲伤` | 2.40 s | −6.4 dB |
| `10-es-angry.wav` | `愤怒` | 1.90 s | −11.7 dB |
| `11-es-happy.wav` | `高兴` | 2.20 s | −4.9 dB |

**B. Can free-text instruction do better than labels?**
`13-es-freeform-en.wav` — "Terrified whisper, trembling, barely able to speak, as
if hiding from something." (2.60 s, −4.4 dB)

**C. Is it the language, or the model?**
| File | Language | Label |
|---|---|---|
| `07-zh-neutral.wav` | zh | `中性` |
| `08-zh-fear.wav` | zh | `恐惧` |
| `12-zh-angry.wav` | zh | `愤怒` |

**D. Speaker-only vs ICL — the fidelity A/B (CUDA, same text/voice/instruct/seed)**

| File | Mode | Duration |
|---|---|---|
| `20-a-speaker-only.wav` | speaker conditioning only | 2.4 s |
| `21-b-icl.wav` | `reference_text` (ICL acoustic prefix) | **5.1 s** |

Same sentence: "Entra. No mires atrás."

**Operator verdict (perceptual, 2026-11-20):** both are heard as the same
narrator family, ~78 % perceived similarity. Differences: ICL (21-b) is more
open, softer and more expressive; speaker-only (20-a) is darker, more compact
and more contained. Naturalness is good in both.

**Decision:** speaker-only stays the default. The ICL take is 2.1x longer for
the same sentence — the model continues the reference instead of reading the
text — and its extra "expressiveness" is that continuation, not acting. Length
control beats a marginal timbre preference in narration, and the emotion is
supposed to come from the instruction, not from the reference.

If a future voice needs ICL fidelity, it should be a per-voice opt-in, never the
default.

`internal/` holds the parameter sweeps (guidance 2/4/7, Spanish freeform,
instruct variants) — kept for the record, not for first listening.

Every clip after `01` says the same thing: "Entra. No mires atrás."
(`01` is the longer smoke line). `01-smoke-es.wav` is 3.90 s, −4.5 dB.

`01` uses: "La casa llevaba veinte años vacía, y aun así alguien cerró la puerta."
`02`–`05` use: "Entra. No mires atrás."

## Commands

```bash
./dist/bin/audiocpp_cli --family ming3_tts --task tts --backend cpu \
  --model models/ming3/ming-3.0-tts-0.5b-q8_0.gguf \
  --text "La casa llevaba veinte años vacía, y aun así alguien cerró la puerta." \
  --request-option language=es --out out/smoke.wav --log

./dist/bin/audiocpp_cli --family ming3_tts --task tts --backend cpu \
  --model models/ming3/ming-3.0-tts-0.5b-q8_0.gguf \
  --text "Entra. No mires atrás." \
  --request-option language=es \
  --request-option template_name=emotion \
  --request-option emotion=恐惧 \
  --out out/label-恐惧.wav
```

## Result

- 3.9 s of 44.1 kHz mono in ~12 s of session time → **RTF ≈ 3.1 on CPU**.
- The emotion label changes duration, waveform hash and peak level, so the
  control has a real effect. Whether it *sounds* frightened is a judgement for
  ears, not for `ffprobe` — that is why the files are kept.

## How to listen

```bash
ffplay -autoexit tests/e2e/ming-smoke/evidence/03-emotion-fear.wav
# or
paplay tests/e2e/ming-smoke/evidence/03-emotion-fear.wav
```

## Linearity (CUDA, resident server)

`examples/guion-10.yaml`, ten lines, one speaker: **29.9 s of audio in 10.2 s
wall time** (~1.0 s per line, RTF 0.34). Model loading is not repeated; the
fixed cost is `up` (1.2 s) + `warm` (0.6 s) + one ffmpeg pass.

## E. Cloning a real human voice (CUDA)

`voice-forge add out/alex.wav --slug alex` registered a 10 s human recording
(converted from MP3 to PCM first — the runtime rejects MP3 disguised as `.wav`).

| File | What it is | Duration |
|---|---|---|
| `22-clone-humano-neutral.wav` | that voice, neutral instruction | 2.5 s |
| `23-clone-humano-miedo.wav` | same voice, `afraid: 0.8` | 2.5 s |

Same sentence, catalog voice `narrador-terror` for comparison: 2.6 s, different
waveform. Zero-shot cloning: the reference is encoded to a speaker embedding per
request; nothing is trained or stored beyond `ref.wav`.

## F. Two characters, one designed + one cloned (CUDA)

`examples/dialogo-dos.yaml`: four lines alternating `narrador-terror` (designed
by prompt) and `alex` (cloned from a human recording), each with its own emotion
and pace.

`24-dialogo-dos-voces.wav` — 12.35 s of audio in 4.5 s wall time.
(Re-rendered after fixing the truncated-pause bug: it was 11.69 s.) Both voices
enter the pipe identically: the catalog lookup does not care where a voice came
from.
