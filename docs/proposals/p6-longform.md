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

**Implementation note (slice A, 2026-11-23).** The marker is a YAML comment:
`yaml.safe_load` deletes it before the parser ever sees it. The split therefore
runs on the **raw text**, on lines matching `^\s*##\s*chapter\b\s*:?\s*(.*)$`
(case-insensitive), and each block is parsed as its own YAML document. A block
that fails to parse is reported with its chapter name, never as a line number
from the whole file.

- Text before the first marker is the script **header**: it may set `title` and
  other global keys, and carrying `lines` there is an error. Those lines would
  become an unnamed chapter, which the output naming cannot represent.
- A marker without a name becomes `chapter N` (`chapter 1`, `chapter 2`, …).
- A block without `lines` is an error that names the chapter.
- A script with no marker is one chapter with the whole document: the previous
  single-file behaviour is unchanged.
- Because splitting is textual, a spoken line inside a YAML block scalar that
  begins with the literal `## chapter:` would be read as a marker. Use a
  quoted single-line `text:` for such a line.

Each chapter is mastered independently by the existing assembler and then
**measured** with `ffmpeg -af loudnorm=print_format=json` (`input_i`). The
measurement is a report: a missing binary or an unreadable reading yields
`None`, never a failed render.

Measured limit: a very short, dynamically peaky chapter cannot reach −14 LUFS
while true peak stays at −1.5 dB (a 1.6 s line measured −16.9 LUFS in an early
run). Two short sentences per chapter land inside the ±1 LUFS acceptance; a
compression stage would be a different, audible decision and is not part of
this slice.

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
