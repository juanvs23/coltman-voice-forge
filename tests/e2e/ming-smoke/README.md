# E2E — Ming-3.0 smoke run (first Spanish synthesis)

Run: 2026-11-20 · commit `a282e4e` of audio.cpp · backend **CPU** ·
model `ming-3.0-tts-0.5b-q8_0.gguf` (1.74 GB, MIT).

## Why this run exists

Before writing the adapter we needed proof of three things: the compiled
runtime executes a GGUF, Ming speaks Spanish, and the emotion controls actually
change the audio. All three were confirmed here. The audio lives in
`evidence/` (gitignored, per the shared E2E rule).

## Files

| File | What it is | Duration | Peak |
|---|---|---|---|
| `01-smoke-es.wav` | First Spanish line, no emotion control | 3.90 s | −4.5 dB |
| `02-emotion-neutral.wav` | Same sentence, `template_name=emotion` + `emotion=中性` | 2.40 s | −1.4 dB |
| `03-emotion-fear.wav` | Same sentence, `emotion=恐惧` | 2.50 s | −4.8 dB |
| `04-instruct-calm.wav` | Same sentence, `instruct="una voz tranquila y neutra"` | 2.70 s | −3.8 dB |
| `05-instruct-terrified.wav` | Same sentence, `instruct="aterrorizada, susurrante, a punto de llorar"` | 2.60 s | −3.7 dB |

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
