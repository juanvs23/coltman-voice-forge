"""Audition without touching the catalog, in three rotating slots."""

from __future__ import annotations

import json

import pytest

from voiceforge.application.preview_service import SLOTS, PreviewService
from voiceforge.domain.errors import VoiceNotFound
from voiceforge.domain.models import Emotion, EmotionAxis, VoiceBrief


@pytest.fixture
def service(catalog_service, repository, synthesizer, tmp_path):
    catalog_service.design(VoiceBrief(description="narrador grave"), slug="narrador", name="Narrador")
    return PreviewService(repository, synthesizer, tmp_path / "out")


def test_preview_renders_the_requested_emotion(service, synthesizer):
    path, duration, slot = service.preview(
        "narrador",
        "Entra.",
        emotion=Emotion(axes={EmotionAxis.AFRAID: 0.9}, intensity=0.8),
    )

    assert slot == 0
    assert path.name == "slot-0.wav"
    assert duration == 1.0
    text, slug, emotion, _speed = synthesizer.calls[0]
    assert text == "Entra."
    assert slug == "narrador"
    assert emotion.axes[EmotionAxis.AFRAID] == 0.9


def test_preview_is_neutral_by_default(service, synthesizer):
    _path, _duration, slot = service.preview("narrador", "Entra.")
    assert slot == 0
    assert synthesizer.calls[0][2].is_neutral is True


def test_preview_does_not_change_the_catalog(service, catalog_service):
    before = catalog_service.get("narrador")
    service.preview("narrador", "Entra.", emotion=Emotion(axes={EmotionAxis.ANGRY: 1.0}))
    assert catalog_service.get("narrador") == before


def test_preview_rejects_an_unknown_slug(service):
    with pytest.raises(VoiceNotFound):
        service.preview("fantasma", "Entra.")


def test_slots_rotate_and_never_grow(service, synthesizer, tmp_path):
    slots = [service.preview("narrador", f"toma {i}")[2] for i in range(6)]

    assert slots == [0, 1, 2, 0, 1, 2]
    previews = sorted((tmp_path / "out" / "previews").glob("*.wav"))
    assert len(previews) == SLOTS


def test_each_slot_keeps_its_own_provenance(service, tmp_path):
    service.preview("narrador", "primera", emotion=Emotion(axes={EmotionAxis.SAD: 0.5}))
    service.preview("narrador", "segunda")

    first = json.loads((tmp_path / "out" / "previews" / "slot-0.json").read_text())
    assert first["text"] == "primera"
    assert first["axes"] == {"sad": 0.5}
    assert first["voice"] == "narrador"


def test_overwriting_replaces_the_metadata(service, tmp_path):
    service.preview("narrador", "vieja")
    for _ in range(SLOTS):
        service.preview("narrador", "nueva")
    payload = json.loads((tmp_path / "out" / "previews" / "slot-0.json").read_text())
    assert payload["text"] == "nueva"
