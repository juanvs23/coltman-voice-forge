"""Audition a catalog voice with any emotion, without touching the catalog.

The neutral rule protects what gets *stored*, not what you may *hear*.

Storage policy: previews live in **three fixed slots** (`slot-0..2.wav`) and are
overwritten on rotation. Auditioning is a disposable act, so the directory has a
constant size instead of growing forever. The oldest slot is recycled, which is
stateless and works across CLI invocations.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..domain.models import Emotion, Voice
from .ports import CatalogRepository, SpeechSynthesizer

SLOTS = 3


class PreviewService:
    def __init__(
        self,
        catalog: CatalogRepository,
        synthesizer: SpeechSynthesizer,
        out_dir: Path,
    ) -> None:
        self._catalog = catalog
        self._synth = synthesizer
        self._out = Path(out_dir) / "previews"

    def preview(
        self,
        slug: str,
        text: str,
        *,
        emotion: Emotion | None = None,
        speed: float = 1.0,
    ) -> tuple[Path, float, int]:
        voice: Voice = self._catalog.get(slug)
        emotion = emotion or Emotion()

        self._out.mkdir(parents=True, exist_ok=True)
        slot = _next_slot(self._out)
        out_path = self._out / f"slot-{slot}.wav"

        duration = self._synth.synthesize(
            text=text,
            voice=voice,
            emotion=emotion,
            speed=speed,
            out_path=out_path,
        )

        # The filename no longer says what the take was, so keep the provenance
        # next to it. Cheap, and it survives the next overwrite cycle.
        (self._out / f"slot-{slot}.json").write_text(
            json.dumps(
                {
                    "slot": slot,
                    "voice": voice.slug,
                    "text": text,
                    "axes": {axis.value: value for axis, value in emotion.axes.items()},
                    "intensity": emotion.intensity,
                    "speed": speed,
                    "duration_s": round(duration, 2),
                    "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return out_path, duration, slot


def _next_slot(directory: Path) -> int:
    """First missing slot, else the oldest one."""
    oldest, oldest_time = 0, None
    for index in range(SLOTS):
        candidate = directory / f"slot-{index}.wav"
        if not candidate.exists():
            return index
        modified = candidate.stat().st_mtime
        if oldest_time is None or modified < oldest_time:
            oldest, oldest_time = index, modified
    return oldest
