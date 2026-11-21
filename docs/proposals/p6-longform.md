# P6 — Long-form delivery

> Task breakdown: [tasks/p6-longform.md](../tasks/p6-longform.md)

## Goal
Narrating a 30-minute script should not produce one opaque WAV, and a script
should be able to mix synthetic lines with the operator's own acted performances.

## Scope

### 1. Chaptered output
`voice-forge render guion.yaml --chapter` splits on a marker (`## chapter`) and
writes `out/<slug>-01.wav`, `-02.wav`… with loudness measured per chapter.

- Why: a 30-minute file cannot be re-rendered cheaply; a chapter can.
- Loudness: each chapter targets −14 LUFS independently, so a quiet scene does
  not drag the whole file down.

### 2. `source:` lines
A line may carry `source: path/to/take.wav` instead of `text`. That line goes
through the converter (P4) into the selected catalog voice, preserving the
operator's performance.

```yaml
lines:
  - voice: alex
    text: "Entra."
    emotion: { afraid: 0.7 }
  - voice: alex
    source: tomas/linea-02.wav     # my own performance, converted
```

- Requires the P4 converter backend.
- `text` and `source` are mutually exclusive; a line with neither is an error.

### 3. Voice versioning
`slug@2` resolves to the latest version of `narrador`, so a script written today
keeps working after the voice is corrected. The catalog stores
`catalog/<slug>/versions/v1|v2/` or a `version` field with the same slug prefix.

- Only worth building when a voice actually needs correcting.

### 4. Duration guard (optional)
One measurement showed a strong emotion producing 25 % more audio than neutral
for the same sentence. A per-line ceiling (`max_duration_factor`) would fail
loudly instead of shipping a bloated line.

- Off by default; the operator asked not to police this yet.

## Acceptance
- A 10-chapter script renders to 10 files, each within ±1 LUFS of target.
- A script mixing `text:` and `source:` lines renders without manual steps.
- An old script still renders after a voice is re-registered as `slug@2`.

## Risks
- Chaptered rendering multiplies queue jobs; the FIFO keeps it serial but the
  operator needs progress, not a frozen console (P3 owns that).
- Versioning adds a second addressing scheme; it must not allow two voices with
  the same slug to coexist silently.
