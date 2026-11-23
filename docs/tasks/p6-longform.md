# P6 — Long-form delivery: task breakdown

Spec: [../proposals/p6-longform.md](../proposals/p6-longform.md)

Four independent slices. Ship them in this order; each is useful on its own.

### Slice A — chapters — shipped (2026-11-23)

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| ✅ P6-1 | Chapter marker in the script (`## chapter: name`) parsed into groups | `domain/script.py` | Parser test: two markers → three groups | S |
| ✅ P6-2 | `render --chapter` writes one file per group with per-chapter loudness | `application/dialogue_service.py`, `cli.py` | 3-chapter script → 3 files, each within ±1 LUFS | M |
| ✅ P6-3 | Report per chapter (path, duration, LUFS) in CLI and API | `cli.py`, `http.py` | Output lists each file and its measurement | S |

**Evidence**
- `tests/unit/test_script_chapters.py` — 9 cases: header + two blocks split into
  three groups, two chapters parsed, unnamed marker → `chapter N`, case-insensitive
  marker, block without `lines` names the chapter, header `lines` refused,
  unknown header keys refused, no marker → one chapter, file loading.
- `tests/unit/test_render_chapters.py` — 3 chapters → `-01..-03.wav`, each
  `lufs=-14.0` from the fake, `duration_s=12.5`, no debris in the output
  directory; `target_lufs=None` skips measuring; the CLI prints three `LUFS`
  lines plus `total  3 chapters`.
- `tests/integration/test_api_chapters.py` — `chapter: true` returns the list;
  without it the response keeps `path`/`lines`/`speakers` and has no `chapters`.
- Real run: `uv run voice-forge render examples/guion-3-capitulos.yaml --out
  /tmp/opencode/caps/narracion.wav --chapter` → 3 files, **−14.89 / −13.82 /
  −14.13 LUFS**, durations **6.00 / 5.00 / 5.55 s**, re-measured with ffmpeg.
- `uv run pytest -q` → **315 passed**.

> Note on the parser test: the header is a group in the splitter (two markers →
> three groups) but not a chapter — a chapter needs `lines`, and the header is
> forbidden to carry them. See the note in the proposal.

### Slice B — acted lines

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P6-4 | `Line.source` alternative to `Line.text`; exactly one is required | `domain/models.py` | Both / neither are rejected with the field name | S |
| P6-5 | `DialogueService` routes `source:` lines through the converter (needs P4) | `application/dialogue_service.py` | A mixed script renders; the converted line keeps the take's timing | M |
| P6-6 | E2E: one synthetic line + one acted line in a single dialogue | `tests/e2e/acted-lines/` | Evidence: both files, the mix, and the timings | M |

### Slice C — voice versioning

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P6-7 | `slug@2` resolution: catalog stores versions, latest wins for bare slug | `adapters/secondary/fs_catalog.py` | Old script renders after a voice is re-registered | M |
| P6-8 | Refuse two versions with the same number; `verify` reports the active one | `fs_catalog.py` | Tests for the collision and for the report | S |

### Slice D — duration guard (optional, off by default)

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| P6-9 | `max_duration_factor` per line, computed from characters × measured rate | `application/dialogue_service.py` | A strong emotion > factor fails loudly instead of shipping | S |
| P6-10 | `--no-guard` escape hatch | `cli.py` | Flag disables it; documented | S |

## Definition of done
A 10-chapter script renders to 10 files within tolerance; a script mixing `text:`
and `source:` renders without manual steps; an old script survives a voice
re-registration.
