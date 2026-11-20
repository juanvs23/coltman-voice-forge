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
