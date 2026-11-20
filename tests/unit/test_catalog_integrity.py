"""The clip is the voice. These tests hold that line."""

from __future__ import annotations

from voiceforge.domain.models import VoiceBrief


def test_registering_records_the_clip_hash(catalog_service):
    voice = catalog_service.register(b"RIFF-original", slug="voz", name="Voz")
    assert voice.ref_sha256 is not None
    assert len(voice.ref_sha256) == 64


def test_verify_passes_on_an_untouched_catalog(catalog_service):
    catalog_service.design(VoiceBrief(description="a"), slug="una")
    catalog_service.register(b"RIFF-otra", slug="otra", name="Otra")
    report = catalog_service.verify()
    assert [item["ok"] for item in report] == [True, True]


def test_verify_detects_a_modified_reference(catalog_service):
    voice = catalog_service.register(b"RIFF-original", slug="voz", name="Voz")
    voice.ref_audio.write_bytes(b"RIFF-TAMPERED")

    report = catalog_service.verify()
    assert report[0]["ok"] is False
    assert report[0]["expected"] != report[0]["actual"]


def test_a_voice_without_a_recorded_hash_is_unverifiable(catalog_service, catalog_dir):
    import json

    catalog_service.register(b"RIFF-x", slug="vieja", name="Vieja")
    payload = json.loads((catalog_dir / "vieja" / "voice.json").read_text())
    payload.pop("ref_sha256")
    (catalog_dir / "vieja" / "voice.json").write_text(json.dumps(payload))

    assert catalog_service.verify()[0]["ok"] is None
