"""Dialogue script parsing.

The on-disk format is YAML because operators edit it by hand. Parsing lives in
the domain: it is a rule, not an adapter.
"""

from __future__ import annotations

from typing import Any, Mapping

import yaml

from .errors import ValidationError
from .models import Dialogue, Emotion, EmotionAxis, Line


def _emotion(raw: Any) -> Emotion:
    if raw is None:
        return Emotion()
    if isinstance(raw, str):
        return Emotion(hint=raw)
    if not isinstance(raw, Mapping):
        raise ValidationError("emotion must be a mapping of axis -> 0..1, or a text hint")

    axes: dict[EmotionAxis, float] = {}
    intensity = 0.6
    hint: str | None = None
    for key, value in raw.items():
        if key == "intensity":
            intensity = float(value)
        elif key == "hint":
            hint = str(value)
        else:
            try:
                axes[EmotionAxis(str(key))] = float(value)
            except ValueError as exc:  # unknown axis
                allowed = ", ".join(a.value for a in EmotionAxis)
                raise ValidationError(f"unknown emotion axis {key!r}; allowed: {allowed}") from exc
    return Emotion(axes=axes, intensity=intensity, hint=hint)


def parse_dialogue(data: Mapping[str, Any]) -> Dialogue:
    """Build a :class:`Dialogue` from already-parsed YAML data."""

    lines_raw = data.get("lines")
    if not isinstance(lines_raw, list) or not lines_raw:
        raise ValidationError("a script needs a non-empty 'lines' list")

    lines: list[Line] = []
    for position, raw in enumerate(lines_raw, start=1):
        if not isinstance(raw, Mapping):
            raise ValidationError(f"line {position} must be a mapping")
        try:
            voice = str(raw["voice"]).strip()
            text = str(raw["text"]).strip()
        except KeyError as exc:
            raise ValidationError(f"line {position} is missing {exc.args[0]!r}") from exc
        lines.append(
            Line(
                voice=voice,
                text=text,
                emotion=_emotion(raw.get("emotion")),
                speed=float(raw.get("speed", 1.0)),
                pause_after_ms=int(raw.get("pause_after_ms", 350)),
            )
        )

    return Dialogue(title=str(data.get("title", "untitled")).strip() or "untitled", lines=tuple(lines))


def load_dialogue(path) -> Dialogue:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, Mapping):
        raise ValidationError("the script root must be a mapping")
    return parse_dialogue(data)
