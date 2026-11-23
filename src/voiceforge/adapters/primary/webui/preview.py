"""Preview screen: render one take through the serial queue.

Nothing here schedules work: ``SerialQueue`` is the only planner and Gradio
only paints. Every function is pure — ``ctx`` in, strings and paths out — so
the four-take rotation can be tested without a browser or a model.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Mapping, Sequence

from ....domain.errors import VoiceForgeError
from ....domain.models import Emotion, EmotionAxis
from .context import UiContext, preview_slots

EMOTION_AXES: tuple[EmotionAxis, ...] = tuple(EmotionAxis)

PREVIEW_TIMEOUT_S = 900


# ── sliders ─────────────────────────────────────────────────────────────
def axes_from(values: Sequence[float]) -> dict[str, float]:
    """Map the eight sliders, in ``EMOTION_AXES`` order, to axis values."""
    return {
        axis.value: float(value)
        for axis, value in zip(EMOTION_AXES, values)
        if value is not None
    }


# ── one take ────────────────────────────────────────────────────────────
def preview_once(
    ctx: UiContext,
    slug: str | None,
    text: str | None,
    axes: Mapping[str, float] | None = None,
    intensity: float | None = 0.6,
    speed: float | None = 1.0,
    hint: str | None = None,
) -> tuple[str | None, str, str]:
    """Render one take. Returns (wav path or None, message, refreshed slots)."""
    target = (slug or "").strip()
    spoken = (text or "").strip()
    if not target:
        return None, "Pick a voice first.", slots_html(ctx)
    if not spoken:
        return None, "Write the text the voice should read.", slots_html(ctx)

    try:
        emotion = Emotion(
            axes={EmotionAxis(key): float(value) for key, value in (axes or {}).items()},
            intensity=float(intensity) if intensity is not None else 0.6,
            hint=(hint or "").strip() or None,
        )
        rate = float(speed) if speed is not None else 1.0
    except (ValueError, TypeError, VoiceForgeError) as exc:
        return None, f"Those emotion settings were rejected: {exc}", slots_html(ctx)

    try:
        job = ctx.queue.submit(
            "preview",
            lambda: ctx.preview.preview(target, spoken, emotion=emotion, speed=rate),
        )
        finished = ctx.queue.wait(job.id, timeout=PREVIEW_TIMEOUT_S)
    except RuntimeError as exc:  # a closed or full queue
        return None, f"The queue refused the job: {exc}", slots_html(ctx)

    if finished.state != "done":
        return None, _failure_message(finished.error), slots_html(ctx)

    path, duration, slot = finished.result
    if not Path(path).is_file():
        return None, f"The take reported {path}, but the file is not there.", slots_html(ctx)
    return (
        str(path),
        f"Take written to slot {slot} ({duration:.2f} s). The previous one was recycled.",
        slots_html(ctx),
    )


def _failure_message(error: str | None) -> str:
    reason = error or "the preview did not finish"
    if "EngineUnavailable" in reason:
        return f"engine is down; run `voice-forge up` — {reason}"
    return f"The take failed: {reason}"


# ── slots ───────────────────────────────────────────────────────────────
def slots_html(ctx: UiContext) -> str:
    """The three fixed slots with a player each, or the reason it is empty."""
    previews = Path(ctx.settings.out_dir) / "previews"
    blocks = [_slot_block(entry, previews) for entry in preview_slots(ctx.settings.out_dir)]
    return '<div class="vf-slots">' + "".join(blocks) + "</div>"


def _slot_block(entry: Mapping[str, object], previews: Path) -> str:
    slot = int(entry["slot"])
    heading = f'<h4 class="vf-slot-title">slot {slot}</h4>'
    if entry.get("empty"):
        return (
            f'<div class="vf-slot vf-slot-empty">\n  {heading}'
            "\n  <p>empty — no take rendered yet.</p>\n</div>"
        )
    axes = entry.get("axes") or {}
    described = ", ".join(
        f"{html.escape(str(key))}={float(value):.2f}"
        for key, value in sorted(dict(axes).items())
    ) or "neutral"
    duration = entry.get("duration_s")
    duration_text = f"{float(duration):.2f} s" if duration is not None else "unknown"
    audio = ""
    if (previews / f"slot-{slot}.wav").is_file():
        audio = (
            f'\n  <audio controls preload="none" '
            f'src="/previews/slot-{slot}.wav"></audio>'
        )
    return (
        f'<div class="vf-slot vf-slot-filled">\n  {heading}'
        f'\n  <p class="vf-slot-voice"><strong>{html.escape(str(entry.get("voice") or "unknown"))}'
        f"</strong> · {duration_text}</p>"
        f'\n  <p class="vf-slot-text">{html.escape(str(entry.get("text") or ""))}</p>'
        f'\n  <p class="vf-slot-axes">{described}</p>{audio}\n</div>'
    )


def slots_payload(ctx: UiContext) -> list[dict]:
    """The same three entries ``GET /api/previews`` reports."""
    return preview_slots(ctx.settings.out_dir)
