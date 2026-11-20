"""Derive a new catalog voice from an existing one.

"Modify a voice" is not something the model does: it is a catalog operation.
Take a reference, transform it, register the result as a new slug with its
provenance recorded. The original is never touched.
"""

from __future__ import annotations

import io
import tempfile
import wave
from pathlib import Path

from ..domain.errors import RenderFailed, ValidationError, VoiceExists, VoiceNotFound
from ..domain.models import NewVoice, Voice
from .ports import CatalogRepository, VoiceTransformer


class DeriveService:
    def __init__(
        self,
        catalog: CatalogRepository,
        transformer: VoiceTransformer,
        clock,
    ) -> None:
        self._catalog = catalog
        self._transformer = transformer
        self._clock = clock

    def derive(
        self,
        source_slug: str,
        *,
        slug: str,
        name: str | None = None,
        pitch_semitones: float = 0.0,
        tags: tuple[str, ...] = (),
    ) -> Voice:
        if not -6.0 <= pitch_semitones <= 6.0:
            raise ValidationError("pitch shift must be within -6..6 semitones")

        try:
            self._catalog.get(slug)
        except VoiceNotFound:
            pass
        else:
            raise VoiceExists(f"slug already in the catalog: {slug}")

        source = self._catalog.get(source_slug)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "derived.wav"
            self._transformer.pitch(source.ref_audio, target, pitch_semitones)
            if not target.exists() or target.stat().st_size == 0:
                raise RenderFailed("the transformation produced no audio")
            audio = target.read_bytes()

        return self._catalog.save(
            NewVoice(
                slug=slug,
                name=(name or f"{source.name} ({pitch_semitones:+.0f} st)").strip(),
                language=source.language,
                sample_rate=_rate(audio),
                recipe={
                    "derived_from": source.slug,
                    "transform": "pitch",
                    "pitch_semitones": pitch_semitones,
                    "source_sha256": source.ref_sha256,
                },
                created_at=self._clock(),
                tags=tuple(tags),
                origin="derived",
                # A transformation does not add emotion: the derived voice keeps
                # the neutrality of its source by construction.
                reference_neutral=source.reference_neutral,
            ),
            audio,
        )


def _rate(audio: bytes) -> int:
    try:
        with wave.open(io.BytesIO(audio), "rb") as handle:
            return int(handle.getframerate())
    except Exception:  # noqa: BLE001
        return 44_100
