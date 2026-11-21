# P5 — Long-form delivery: task breakdown

Spec: [../proposals/p5-longform.md](../proposals/p5-longform.md)

Four independent slices. Ship them in this order; each is useful on its own.

### Slice A — chapters

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P5-1 | Chapter marker in the script (`## chapter: name`) parsed into groups | `domain/script.py` | Parser test: two markers → three groups | S |
| P5-2 | `render --chapter` writes one file per group with per-chapter loudness | `application/dialogue_service.py`, `cli.py` | 3-chapter script → 3 files, each within ±1 LUFS | M |
| P5-3 | Report per chapter (path, duration, LUFS) in CLI and API | `cli.py`, `http.py` | Output lists each file and its measurement | S |

### Slice B — acted lines

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P5-4 | `Line.source` alternative to `Line.text`; exactly one is required | `domain/models.py` | Both / neither are rejected with the field name | S |
| P5-5 | `DialogueService` routes `source:` lines through the converter (needs P4) | `application/dialogue_service.py` | A mixed script renders; the converted line keeps the take's timing | M |
| P5-6 | E2E: one synthetic line + one acted line in a single dialogue | `tests/e2e/acted-lines/` | Evidence: both files, the mix, and the timings | M |

### Slice C — voice versioning

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P5-7 | `slug@2` resolution: catalog stores versions, latest wins for bare slug | `adapters/secondary/fs_catalog.py` | Old script renders after a voice is re-registered | M |
| P5-8 | Refuse two versions with the same number; `verify` reports the active one | `fs_catalog.py` | Tests for the collision and for the report | S |

### Slice D — duration guard (optional, off by default)

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P5-9 | `max_duration_factor` per line, computed from characters × measured rate | `application/dialogue_service.py` | A strong emotion > factor fails loudly instead of shipping | S |
| P5-10 | `--no-guard` escape hatch | `cli.py` | Flag disables it; documented | S |

## Definition of done
A 10-chapter script renders to 10 files within tolerance; a script mixing `text:`
and `source:` renders without manual steps; an old script survives a voice
re-registration.
