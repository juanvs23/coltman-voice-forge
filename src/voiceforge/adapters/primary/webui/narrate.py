"""Narrate screen: validate a script, estimate it and render it.

``render_script`` is a generator on purpose: a render owns the GPU for seconds
or minutes, so it yields the queue state on every poll instead of blocking the
page until the file exists. ``SerialQueue`` stays the only planner; this module
submits the job and paints its state.

Every other function is pure — text in, numbers and sentences out — so the
validation and the estimate are testable without a browser or a model.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterator, Mapping

import yaml

from ....domain.errors import VoiceForgeError
from ....domain.script import parse_dialogue
from .context import UiContext, queue_line

# Measured on CUDA on 2026-11-23: ten rendered lines took 32 s, so a line costs
# ~3.2 s of model work. The estimate is a planning aid, not a promise: voice,
# emotion and speed move the real number, which is why every message says so.
SECONDS_PER_LINE = 3.2

POLL_INTERVAL_S = 0.2
RENDER_TIMEOUT_S = 3600


# ── validation ──────────────────────────────────────────────────────────
def validate_script(text: str | None) -> tuple[int, str]:
    """Parse a YAML script. Returns ``(lines, error)``; ``error`` is empty when valid."""
    try:
        dialogue = _dialogue(text)
    except (yaml.YAMLError, VoiceForgeError, TypeError, ValueError) as exc:
        return 0, _reason(exc)
    return len(dialogue.lines), ""


def _dialogue(text: str | None):
    """Parse the text the way the API does, so both paths accept the same scripts."""
    try:
        data = yaml.safe_load(text or "") or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"the YAML is not valid: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ValueError("the script root must be a mapping with a 'lines' list")
    return parse_dialogue(data)


def _reason(exc: BaseException) -> str:
    """One operator sentence, never a traceback."""
    return str(exc).strip() or exc.__class__.__name__


# ── estimate ────────────────────────────────────────────────────────────
def estimate_script(text: str | None) -> tuple[int, float, int, str]:
    """Return ``(lines, seconds, pauses_ms, message)`` for a script.

    ``seconds`` is ``lines × SECONDS_PER_LINE`` plus the declared pauses. The
    message always labels it as an estimate.
    """
    try:
        dialogue = _dialogue(text)
    except (yaml.YAMLError, VoiceForgeError, TypeError, ValueError) as exc:
        return 0, 0.0, 0, f"**Script rejected** — {_reason(exc)}"

    lines = len(dialogue.lines)
    pauses_ms = sum(line.pause_after_ms for line in dialogue.lines)
    seconds = lines * SECONDS_PER_LINE + pauses_ms / 1000.0
    message = (
        f"**Estimation** (not a promise): {lines} line{'s' if lines != 1 else ''} "
        f"× {SECONDS_PER_LINE:.1f} s + {pauses_ms} ms of pauses ≈ {seconds:.1f} s. "
        "The real duration depends on each line's voice, emotion and speed."
    )
    return lines, seconds, pauses_ms, message


def resolved_out(ctx: UiContext, out_path: str | None) -> Path:
    """The file a render writes: the operator's path, or ``out/narrate.wav``."""
    chosen = (out_path or "").strip()
    if chosen:
        return Path(chosen).expanduser()
    return Path(ctx.settings.out_dir) / "narrate.wav"


# ── render ──────────────────────────────────────────────────────────────
def render_script(
    ctx: UiContext,
    script: str | None,
    out_path: str | None,
    master: bool,
) -> Iterator[tuple[str, str]]:
    """Render a script, yielding ``(message, queue_line)`` while it runs.

    The first yield is either the validation error (and then the generator
    stops) or the progress of a submitted job. Every poll re-reads the queue,
    so the operator sees ``busy``/``pending`` instead of a frozen page.
    """
    lines, error = validate_script(script)
    if error:
        yield f"**Script rejected** — {error}", _queue(ctx)
        return

    target = resolved_out(ctx, out_path)
    unwritable = _unwritable(target)
    if unwritable:
        yield (
            f"**Cannot write to `{target}`** — {unwritable}. Choose another "
            "output path and try again.",
            _queue(ctx),
        )
        return

    dialogue = _dialogue(script)
    target_lufs = float(ctx.settings.default_lufs) if master else None

    try:
        job = ctx.queue.submit(
            "render",
            lambda: ctx.dialogue.render(dialogue, target, target_lufs=target_lufs),
        )
    except RuntimeError as exc:  # a closed or full queue
        yield f"**The queue refused the job** — {exc}", _queue(ctx)
        return

    deadline = time.monotonic() + RENDER_TIMEOUT_S
    while True:
        state = ctx.queue.get(job.id).state
        if state in {"done", "failed"}:
            break
        if time.monotonic() > deadline:
            yield (
                f"**Render timed out** — `{target}` is not finished after "
                f"{RENDER_TIMEOUT_S} s. The job may still be in the queue.",
                _queue(ctx),
            )
            return
        yield (
            f"Rendering {lines} line{'s' if lines != 1 else ''} to `{target}`… "
            f"job `{job.id}`",
            _queue(ctx),
        )
        time.sleep(POLL_INTERVAL_S)

    finished = ctx.queue.get(job.id)
    if finished.state != "done":
        yield _failure(finished.error), _queue(ctx)
        return

    result = finished.result
    yield (
        f"**Rendered** {result.lines} line"
        f"{'s' if result.lines != 1 else ''} to `{result.path}` — "
        f"duration {result.duration_s:.2f} s.",
        _queue(ctx),
    )


def _unwritable(target: Path) -> str:
    """Empty when the file can be written, otherwise the reason."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return str(exc) or "the directory could not be created"
    if target.exists() and not target.is_file():
        return "a directory is in the way"
    if not os.access(target.parent, os.W_OK):
        return "the directory is not writable"
    if target.exists() and not os.access(target, os.W_OK):
        return "the file is not writable"
    return ""


def _failure(error: str | None) -> str:
    reason = error or "the render did not finish"
    if "EngineUnavailable" in reason:
        return f"**Engine is down** — run `voice-forge up` and try again. {reason}"
    if "ValidationError" in reason:
        return f"**Render rejected** — {reason.split('ValidationError:', 1)[-1].strip()}"
    return f"**Render failed** — {reason}"


def _queue(ctx: UiContext) -> str:
    return queue_line(ctx.queue.snapshot())
