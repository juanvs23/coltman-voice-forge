"""Derive a new catalog voice from an existing one.

"Modify a voice" is not something the model does: it is a catalog operation.
Take a reference, transform it, register the result as a new slug with its
provenance recorded. The original is never touched.

Two transforms exist: a pitch/formant shift (no model, instant) and a timbre
conversion that borrows the identity of a second voice (one model process).
They are mutually exclusive: one derivation has one purpose.
"""

from __future__ import annotations

import io
import tempfile
import wave
from pathlib import Path

from ..domain.errors import RenderFailed, ValidationError, VoiceExists, VoiceNotFound
from ..domain.models import NewVoice, Voice
from .ports import CatalogRepository, TimbreTransformer, VoiceTransformer


class DeriveService:
    def __init__(
        self,
        catalog: CatalogRepository,
        transformer: VoiceTransformer,
        clock,
        timbre: TimbreTransformer | None = None,
    ) -> None:
        self._catalog = catalog
        self._transformer = transformer
        self._clock = clock
        # Optional so a deployment without the conversion model still derives
        # by pitch; asking for a timbre without it is a clear validation error.
        self._timbre = timbre

    def derive(
        self,
        source_slug: str,
        *,
        slug: str,
        name: str | None = None,
        pitch_semitones: float | None = None,
        timbre_from: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> Voice:
        if pitch_semitones is not None and timbre_from is not None:
            raise ValidationError("choose pitch or timbre, not both")
        if pitch_semitones is None and timbre_from is None:
            raise ValidationError("derive needs a pitch shift or a timbre source")
        if timbre_from is not None and self._timbre is None:
            raise ValidationError("timbre conversion is not configured")

        if pitch_semitones is not None and not -6.0 <= pitch_semitones <= 6.0:
            raise ValidationError("pitch shift must be within -6..6 semitones")

        try:
            self._catalog.get(slug)
        except VoiceNotFound:
            pass
        else:
            raise VoiceExists(f"slug already in the catalog: {slug}")

        source = self._catalog.get(source_slug)
        target = self._catalog.get(timbre_from) if timbre_from else None

        with tempfile.TemporaryDirectory() as tmp:
            derived = Path(tmp) / "derived.wav"
            if target is not None:
                assert self._timbre is not None  # guarded by the check above
                self._timbre.timbre(source.ref_audio, target.ref_audio, derived)
            else:
                assert pitch_semitones is not None  # the two checks above
                self._transformer.pitch(source.ref_audio, derived, pitch_semitones)
            if not derived.exists() or derived.stat().st_size == 0:
                raise RenderFailed("the transformation produced no audio")
            audio = derived.read_bytes()

        if target is not None:
            recipe = {
                "derived_from": source.slug,
                "transform": "timbre",
                "timbre_from": target.slug,
                "source_sha256": source.ref_sha256,
                "timbre_sha256": target.ref_sha256,
                "model": "tone-color-vc-f16",
            }
            default_name = f"{source.name} como {target.name}"
        else:
            recipe = {
                "derived_from": source.slug,
                "transform": "pitch",
                "pitch_semitones": pitch_semitones,
                "source_sha256": source.ref_sha256,
            }
            default_name = f"{source.name} ({pitch_semitones:+.0f} st)"

        return self._catalog.save(
            NewVoice(
                slug=slug,
                name=(name or default_name).strip(),
                language=source.language,
                sample_rate=_rate(audio),
                recipe=recipe,
                created_at=self._clock(),
                tags=tuple(tags),
                origin="derived",
                # The performance is the source clip's; the target contributes
                # timbre only. So a neutral source stays neutral, and no emotion
                # can be smuggled in by the target's reference.
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
