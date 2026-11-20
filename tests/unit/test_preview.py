"""Audition without touching the catalog. The neutral rule protects storage."""

from __future__ import annotations

import pytest

from voiceforge.application.preview_service import PreviewService
from voiceforge.domain.errors import VoiceNotFound
from voiceforge.domain.models import Emotion, EmotionAxis, VoiceBrief


@pytest.fixture
def service(catalog_service, repository, synthesizer, tmp_path):
    catalog_service.design(VoiceBrief(description="narrador grave"), slug="narrador", name="Narrador")
    return PreviewService(repository, synthesizer, tmp_path / "out")


def test_preview_renders_the_requested_emotion(service, synthesizer):
    path, duration = service.preview(
        "narrador",
        "Entra.",
        emotion=Emotion(axes={EmotionAxis.AFRAID: 0.9}, intensity=0.8),
    )

    assert path.parent.name == "previews"
    assert path.name == "narrador-afraid.wav"
    assert duration == 1.0
    text, slug, emotion, _speed = synthesizer.calls[0]
    assert text == "Entra."
    assert slug == "narrador"
    assert emotion.axes[EmotionAxis.AFRAID] == 0.9
    assert emotion.intensity == 0.8


def test_preview_defaults_to_neutral(service, synthesizer):
    path, _ = service.preview("narrador", "Entra.")
    assert path.name == "narrador-neutral.wav"
    assert synthesizer.calls[0][2].is_neutral is True


def test_preview_does_not_change_the_catalog(service, catalog_service):
    before = catalog_service.get("narrador")
    service.preview("narrador", "Entra.", emotion=Emotion(axes={EmotionAxis.ANGRY: 1.0}))
    after = catalog_service.get("narrador")
    assert after == before
    assert after.reference_neutral is True


def test_preview_rejects_an_unknown_slug(service):
    with pytest.raises(VoiceNotFound):
        service.preview("fantasma", "Entra.")


def test_previewing_an_emotional_voice_is_allowed(catalog_service, repository, synthesizer, tmp_path):
    """The flag gates storage, never audition."""
    catalog_service.design(VoiceBrief(description="voz aterrada"), slug="voz-miedo", neutral=False)
    service = PreviewService(repository, synthesizer, tmp_path / "out")

    path, _ = service.preview("voz-miedo", "Entra.", emotion=Emotion())
    assert path.exists()
