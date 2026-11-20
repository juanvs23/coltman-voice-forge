"""Domain entities.

Pure Python. Nothing here may import a model SDK, HTTP client or file-system
library beyond the stdlib. If you are tempted to add a model name, that
belongs in an adapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping

from .errors import ValidationError

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")


class EmotionAxis(str, Enum):
    """The eight axes every adapter must be able to approximate."""

    HAPPY = "happy"
    ANGRY = "angry"
    SAD = "sad"
    AFRAID = "afraid"
    DISGUSTED = "disgusted"
    MELANCHOLIC = "melancholic"
    SURPRISED = "surprised"
    CALM = "calm"


@dataclass(frozen=True)
class Emotion:
    """Provider-agnostic emotional direction for a single line.

    ``axes`` are intensities in 0..1. ``intensity`` is the global strength
    (the adapter maps it to ``emo_alpha``, instruction weight, or whatever the
    provider offers). ``hint`` is free text for providers that understand
    descriptions; adapters that do not must ignore it, never fail on it.
    """

    axes: Mapping[EmotionAxis, float] = field(default_factory=dict)
    intensity: float = 0.6
    hint: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.intensity <= 1.0:
            raise ValidationError("intensity must be within 0..1")
        for axis, value in self.axes.items():
            if not isinstance(axis, EmotionAxis):
                raise ValidationError(f"unknown emotion axis: {axis!r}")
            if not 0.0 <= float(value) <= 1.0:
                raise ValidationError(f"{axis.value} must be within 0..1")

    @property
    def is_neutral(self) -> bool:
        return not self.axes and not self.hint

    def dominant(self) -> EmotionAxis | None:
        if not self.axes:
            return None
        return max(self.axes.items(), key=lambda item: item[1])[0]

    def normalised(self) -> "Emotion":
        """Sorted axes, so serialisation is deterministic."""
        return Emotion(
            axes={axis: float(value) for axis, value in sorted(self.axes.items(), key=lambda i: i[0].value)},
            intensity=float(self.intensity),
            hint=self.hint,
        )


@dataclass(frozen=True)
class VoiceBrief:
    """What the operator asks for when creating a voice from text."""

    description: str
    language: str = "Spanish"
    candidates: int = 1
    seed: int | None = None
    preview_text: str | None = None

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValidationError("a voice brief needs a description")
        if not 1 <= self.candidates <= 8:
            raise ValidationError("candidates must be within 1..8")


@dataclass(frozen=True)
class DesignCandidate:
    """One generated voice, still unregistered."""

    index: int
    audio: bytes
    sample_rate: int
    recipe: Mapping[str, object]


@dataclass(frozen=True)
class NewVoice:
    """Everything needed to register a voice, before the repository assigns a path."""

    slug: str
    name: str
    language: str
    sample_rate: int
    recipe: Mapping[str, object]
    created_at: str
    ref_transcript: str | None = None
    tags: tuple[str, ...] = ()
    origin: str = "designed"


@dataclass(frozen=True)
class Voice:
    """A catalog entry. Immutable: changing a voice means a new slug."""

    slug: str
    name: str
    ref_audio: Path
    language: str
    sample_rate: int
    recipe: Mapping[str, object]
    created_at: str
    ref_transcript: str | None = None
    tags: tuple[str, ...] = ()
    origin: str = "designed"
    ref_sha256: str | None = None

    def __post_init__(self) -> None:
        if not SLUG_RE.match(self.slug):
            raise ValidationError(
                "slug must be lowercase letters, digits and dashes (2..49 chars)"
            )
        if not self.name.strip():
            raise ValidationError("a voice needs a name")
        if self.origin not in {"designed", "imported"}:
            raise ValidationError("origin must be 'designed' or 'imported'")
        if self.sample_rate <= 0:
            raise ValidationError("sample_rate must be positive")


@dataclass(frozen=True)
class Line:
    """One spoken turn in a dialogue."""

    voice: str
    text: str
    emotion: Emotion = field(default_factory=Emotion)
    speed: float = 1.0
    pause_after_ms: int = 350

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValidationError("a line cannot be empty")
        if not 0.5 <= self.speed <= 2.0:
            raise ValidationError("speed must be within 0.5..2.0")
        if not 0 <= self.pause_after_ms <= 10_000:
            raise ValidationError("pause_after_ms must be within 0..10000")


@dataclass(frozen=True)
class Dialogue:
    """An ordered script. Voices are referenced by catalog slug."""

    title: str
    lines: tuple[Line, ...]

    def __post_init__(self) -> None:
        if not self.lines:
            raise ValidationError("a dialogue needs at least one line")

    @property
    def speakers(self) -> tuple[str, ...]:
        seen: list[str] = []
        for line in self.lines:
            if line.voice not in seen:
                seen.append(line.voice)
        return tuple(seen)


@dataclass(frozen=True)
class RenderResult:
    path: Path
    duration_s: float
    lines: int
    speakers: tuple[str, ...]
