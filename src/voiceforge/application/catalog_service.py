"""Use cases for the voice catalog.

Rule of this layer: it orchestrates ports. It never knows what a model is.
"""

from __future__ import annotations

import re
from typing import Callable, Sequence

from ..domain.errors import ValidationError, VoiceExists, VoiceNotFound
from ..domain.models import (
    DesignCandidate,
    NewVoice,
    Voice,
    VoiceBrief,
)
from .ports import CatalogRepository, VoiceDesigner

# Emotion words (es/en) from the eight axes we expose. Delivery words such as
# "susurrante" or "lento" are deliberately absent: they are style, not emotion,
# and a neutral narrator may legitimately use them.
# Stems, not whole words: Spanish inflects (enfadado/enfadada/enfadados) and a
# fixed list would miss half of them. Delivery words such as "susurrante" or
# "pausado" are deliberately absent: they are style, not emotion.
EMOTION_STEMS = (
    "alegr", "feliz", "eufóric",
    "enfad", "furios", "rabios", "iracund",
    "trist", "apenad", "desolad",
    "aterrad", "asustad", "miedos", "aterrorizad", "temeros",
    "asqueros", "repugnan",
    "melancólic", "nostálgic", "abatid",
    "sorprend", "asombrad", "estupefact",
    # full forms only, so "contenido" is not read as "contento"
    "contento", "contenta", "contentos", "contentas",
)
EMOTION_WORDS_EN = (
    "happy", "angry", "sad", "afraid", "scared", "disgusted",
    "melancholic", "surprised", "furious", "terrified",
)


def emotional_words(text: str) -> list[str]:
    """Which emotion words a description uses, if any.

    Whole words only: substring matching flagged "pausado" because it contains
    "sad", which turned a neutral brief into an error.
    """
    if not text:
        return []
    lowered = text.lower()
    found: set[str] = set()
    for stem in EMOTION_STEMS:
        # Report the word actually written, not the stem: "aterrado", not "aterrad".
        found |= {
            match.group(0)
            for match in re.finditer(rf"(?<!\w){re.escape(stem)}\w*(?!\w)", lowered)
        }
    for word in EMOTION_WORDS_EN:
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", lowered):
            found.add(word)
    return sorted(found)


class CatalogService:
    def __init__(
        self,
        catalog: CatalogRepository,
        designer: VoiceDesigner,
        clock: Callable[[], str],
    ) -> None:
        self._catalog = catalog
        self._designer = designer
        self._clock = clock

    # ── read ────────────────────────────────────────────────────────────
    def list(self) -> Sequence[Voice]:
        return self._catalog.list()

    def get(self, slug: str) -> Voice:
        return self._catalog.get(slug)

    def remove(self, slug: str) -> None:
        self._catalog.remove(slug)

    def verify(self) -> Sequence[dict]:
        """Every voice must still be the clip that was registered."""
        return self._catalog.verify()

    # ── write ───────────────────────────────────────────────────────────
    def design(
        self,
        brief: VoiceBrief,
        *,
        slug: str,
        name: str | None = None,
        pick: int = 0,
        tags: Sequence[str] = (),
        neutral: bool = True,
    ) -> tuple[Voice, Sequence[DesignCandidate]]:
        """Generate candidates, register the chosen one, return all of them.

        The generated clip enters the catalog through the same door as an
        imported clip, which is what makes "design once, clone forever" work.
        """

        if self._exists(slug):
            raise VoiceExists(f"slug already in the catalog: {slug}")
        self._require_neutral(brief.description, neutral)

        candidates = list(self._designer.design(brief))
        if not candidates:
            raise ValidationError("the designer returned no candidates")
        if not 0 <= pick < len(candidates):
            raise ValidationError(f"pick must be within 0..{len(candidates) - 1}")

        chosen = candidates[pick]
        voice = self._register(
            chosen.audio,
            NewVoice(
                slug=slug,
                name=(name or slug).strip(),
                language=brief.language,
                sample_rate=chosen.sample_rate,
                recipe={
                    "brief": brief.description,
                    "language": brief.language,
                    "seed": brief.seed,
                    "preview_text": brief.preview_text,
                    "candidates": len(candidates),
                    "picked": pick,
                    **dict(chosen.recipe),
                },
                created_at=self._clock(),
                tags=tuple(tags),
                origin="designed",
                reference_neutral=neutral,
            ),
        )
        return voice, candidates

    def register(
        self,
        audio: bytes,
        *,
        slug: str,
        name: str,
        language: str = "Spanish",
        sample_rate: int = 24_000,
        transcript: str | None = None,
        recipe: dict | None = None,
        tags: Sequence[str] = (),
        origin: str = "imported",
        neutral: bool = True,
    ) -> Voice:
        """Register a clip as a catalog voice (the clone path).

        ``origin="designed"`` is used when the clip was generated by a
        voice-design model: it is still an imported clip mechanically, but the
        recipe says where it came from.
        """

        if self._exists(slug):
            raise VoiceExists(f"slug already in the catalog: {slug}")
        self._require_neutral(str((recipe or {}).get("instruct", "")), neutral)
        return self._register(
            audio,
            NewVoice(
                slug=slug,
                name=name.strip(),
                language=language,
                sample_rate=sample_rate,
                recipe=dict(recipe or {"source": "external"}),
                created_at=self._clock(),
                ref_transcript=transcript,
                tags=tuple(tags),
                origin=origin,
                reference_neutral=neutral,
            ),
        )

    # ── internals ───────────────────────────────────────────────────────
    def _exists(self, slug: str) -> bool:
        try:
            self._catalog.get(slug)
        except VoiceNotFound:
            return False
        return True

    @staticmethod
    def _require_neutral(text: str, neutral: bool) -> None:
        """A catalog voice is a neutral identity unless the operator says otherwise."""
        if neutral:
            found = emotional_words(text)
            if found:
                raise ValidationError(
                    f"the description carries emotion ({', '.join(found)}), but a catalog "
                    "voice must be neutral: emotion belongs to each line. Either remove "
                    "those words or pass --emotional to accept a non-neutral reference."
                )

    def _register(self, audio: bytes, new: NewVoice) -> Voice:
        if not audio:
            raise ValidationError("refusing to register an empty audio clip")
        return self._catalog.save(new, audio)
