"""Audition a catalog voice with any emotion, without touching the catalog.

The neutral rule protects what gets *stored*, not what you may *hear*. Trying a
voice with a specific emotion is how you decide whether to keep it, so previews
are a first-class read-only operation.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..domain.models import Emotion, Voice
from .ports import CatalogRepository, SpeechSynthesizer


class PreviewService:
    def __init__(
        self,
        catalog: CatalogRepository,
        synthesizer: SpeechSynthesizer,
        out_dir: Path,
    ) -> None:
        self._catalog = catalog
        self._synth = synthesizer
        self._out = Path(out_dir)

    def preview(
        self,
        slug: str,
        text: str,
        *,
        emotion: Emotion | None = None,
        speed: float = 1.0,
        label: str | None = None,
    ) -> tuple[Path, float]:
        voice: Voice = self._catalog.get(slug)
        emotion = emotion or Emotion()
        name = _safe_name(label or _label_for(emotion))
        out_path = self._out / "previews" / f"{voice.slug}-{name}.wav"
        duration = self._synth.synthesize(
            text=text,
            voice=voice,
            emotion=emotion,
            speed=speed,
            out_path=out_path,
        )
        return out_path, duration


def _label_for(emotion: Emotion) -> str:
    dominant = emotion.dominant()
    return dominant.value if dominant else "neutral"


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "neutral"
