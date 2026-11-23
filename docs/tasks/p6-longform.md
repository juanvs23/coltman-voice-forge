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

### Slice B — acted lines — shipped (2026-11-23)

| # | Task | Files | Check | Size |
|---|---|---|---|---|
| ✅ P6-4 | `Line.source` alternative to `Line.text`; exactly one is required | `domain/models.py`, `domain/script.py` | Both / neither are rejected, naming the line and both fields | S |
| ✅ P6-5 | `DialogueService` routes `source:` lines through the P5 converter; relative paths resolve against `base_dir`; duration read from the produced wav | `application/dialogue_service.py`, `container.py` | A mixed script renders; the converted line keeps the take's timing | M |
| ✅ P6-6 | E2E: one synthetic line + one acted line in a single dialogue | `tests/e2e/acted-lines/` | Evidence: both segments, the mix, and the timings | M |

**Evidence**
- `tests/unit/test_acted_lines.py` — 8 cases: `source` alone parses; `text` +
  `source` rejected with `line 1` and both field names; neither rejected;
  direct `Line(...)` refuses both invalid shapes; a relative `source` resolves
  against the script folder (`load_dialogue` → `base_dir`); a mixed render calls
  the converter **once** with the acted line's voice reference and reads the
  converted duration from the produced wav (the fake converter returns nothing);
  no converter → `ValidationError("this render has acted lines but no converter
  is configured")`; a missing take → `ValidationError` with its resolved path.
- `tests/integration/test_api.py::test_render_accepts_an_acted_source_line` —
  `POST /api/dialogues/render` with one `text:` and one `source:` line returns
  200, 2 lines, and the fake converter is called once.
- E2E `tests/e2e/acted-lines/` — real engine + real converter:
  `01-synthetic.wav` **2.300 s**, `02-acted-converted.wav` **10.170 s** from a
  **10.176 s** take, `03-mixed.wav` **12.870 s** = 2.300 + 0.400 pause +
  10.170354. `verify` reports all catalog voices `ok`.
- `uv run pytest -q` → **324 passed**.

### Deferred — not in P6

| # | Task | Why it is not built |
|---|---|---|
| C. Voice versioning (`slug@2`) | Deferred (2026-11-23). A bare name that follows the latest version would silently change what an old script means. The backlog keeps the explicit form (`voice: narrador@2`) for the day a real correction needs it |
| D. Duration guard | Deferred by the operator: off by default, not policed |

## Definition of done
P6 is done when a 10-chapter script renders to 10 files within tolerance and a
script mixing `text:` and `source:` renders without manual steps. Both hold:
−14.89 / −13.82 / −14.13 LUFS for three chapters, and a mixed 12.670 s render
(synthetic + pause + converted take). Versioning and the guard are backlog
items, not open tasks.
