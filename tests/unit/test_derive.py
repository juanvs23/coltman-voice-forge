"""Deriving a voice from another: the catalog operation, not a model feature."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from voiceforge.application.derive_service import DeriveService
from voiceforge.domain.errors import (
    RenderFailed,
    ValidationError,
    VoiceExists,
    VoiceNotFound,
)
from voiceforge.domain.models import VoiceBrief


def wav_bytes(rate: int = 44_100) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * 1000)
    return buffer.getvalue()


class FakeTransformer:
    def __init__(self, rate: int = 44_100, empty: bool = False) -> None:
        self.calls: list[tuple[Path, float]] = []
        self.rate = rate
        self.empty = empty

    def pitch(self, source: Path, out_path: Path, semitones: float) -> None:
        self.calls.append((Path(source), semitones))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"" if self.empty else wav_bytes(self.rate))


@pytest.fixture
def service(repository, clock):
    return DeriveService(repository, FakeTransformer(), clock)


@pytest.fixture
def source_voice(catalog_service):
    return catalog_service.register(wav_bytes(), slug="alex", name="Alex")


def test_derive_registers_a_new_voice_with_provenance(service, source_voice, catalog_service, repository):
    derived = service.derive("alex", slug="alex-grave", pitch_semitones=-3.0, name="Alex grave")

    assert derived.slug == "alex-grave"
    assert derived.origin == "derived"
    assert derived.recipe["derived_from"] == "alex"
    assert derived.recipe["pitch_semitones"] == -3.0
    assert derived.recipe["transform"] == "pitch"
    assert derived.sample_rate == 44_100
    assert derived.reference_neutral is True

    # the source is untouched
    assert catalog_service.get("alex").slug == "alex"
    assert [v.slug for v in repository.list()] == ["alex", "alex-grave"]


def test_derive_inherits_a_non_neutral_source(catalog_service, repository, clock):
    catalog_service.design(VoiceBrief(description="voz aterrada"), slug="miedo", neutral=False)
    service = DeriveService(repository, FakeTransformer(), clock)
    derived = service.derive("miedo", slug="miedo-grave", pitch_semitones=-2)
    assert derived.reference_neutral is False


def test_derive_refuses_an_existing_slug(service, source_voice):
    with pytest.raises(VoiceExists):
        service.derive("alex", slug="alex", pitch_semitones=-2)


def test_derive_refuses_an_unknown_source(service):
    with pytest.raises(VoiceNotFound):
        service.derive("fantasma", slug="otra", pitch_semitones=-2)


def test_derive_refuses_an_absurd_pitch(service, source_voice):
    with pytest.raises(ValidationError):
        service.derive("alex", slug="otra", pitch_semitones=-12)


def test_an_empty_transformation_is_an_error(repository, clock, source_voice):
    service = DeriveService(repository, FakeTransformer(empty=True), clock)
    with pytest.raises(RenderFailed):
        service.derive("alex", slug="alex-grave", pitch_semitones=-2)


def test_the_transformer_receives_the_source_clip(service, source_voice, repository):
    fake = FakeTransformer()
    service = DeriveService(repository, fake, lambda: "2026-11-20T00:00:00+00:00")
    service.derive("alex", slug="alex-x", pitch_semitones=2.5)

    source_path, semitones = fake.calls[0]
    assert source_path == source_voice.ref_audio
    assert semitones == 2.5
