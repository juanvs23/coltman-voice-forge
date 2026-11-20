from __future__ import annotations

import json

import pytest

from voiceforge.domain.errors import VoiceExists, VoiceNotFound
from voiceforge.domain.models import VoiceBrief


def test_design_registers_the_picked_candidate(catalog_service, designer, catalog_dir):
    brief = VoiceBrief(description="narrador grave", candidates=3)
    voice, candidates = catalog_service.design(brief, slug="narrador", pick=2, name="Narrador")

    assert len(candidates) == 3
    assert voice.slug == "narrador"
    assert voice.origin == "designed"
    assert voice.ref_audio.exists()
    assert voice.recipe["picked"] == 2
    assert voice.recipe["brief"] == "narrador grave"

    payload = json.loads((catalog_dir / "narrador" / "voice.json").read_text())
    assert payload["origin"] == "designed"
    assert (catalog_dir / "narrador" / "GUIDE.md").exists()
    assert (catalog_dir / "narrador" / "ref.wav").read_bytes().startswith(b"RIFF")


def test_design_rejects_taken_slug(catalog_service):
    catalog_service.design(VoiceBrief(description="a"), slug="voz")
    with pytest.raises(VoiceExists):
        catalog_service.design(VoiceBrief(description="b"), slug="voz")


def test_design_rejects_out_of_range_pick(catalog_service):
    from voiceforge.domain.errors import ValidationError

    with pytest.raises(ValidationError):
        catalog_service.design(VoiceBrief(description="a", candidates=2), slug="voz", pick=5)


def test_register_external_clip_is_imported(catalog_service):
    voice = catalog_service.register(
        b"RIFF-external", slug="clon", name="Clon", transcript="hola"
    )
    assert voice.origin == "imported"
    assert voice.ref_transcript == "hola"


def test_get_and_remove(catalog_service):
    catalog_service.design(VoiceBrief(description="a"), slug="voz")
    assert catalog_service.get("voz").slug == "voz"

    catalog_service.remove("voz")
    with pytest.raises(VoiceNotFound):
        catalog_service.get("voz")


def test_empty_audio_is_refused(catalog_service):
    from voiceforge.domain.errors import ValidationError

    with pytest.raises(ValidationError):
        catalog_service.register(b"", slug="voz", name="Voz")


def test_listing_is_sorted_and_skips_partial_dirs(catalog_service, catalog_dir):
    catalog_service.design(VoiceBrief(description="a"), slug="zeta")
    catalog_service.design(VoiceBrief(description="b"), slug="alfa")
    (catalog_dir / "a-medias").mkdir()
    assert [voice.slug for voice in catalog_service.list()] == ["alfa", "zeta"]
