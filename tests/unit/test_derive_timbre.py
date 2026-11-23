"""Derive by timbre: borrow a second voice's identity, keep the performance."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from voiceforge.adapters.primary.cli import build_parser
from voiceforge.application.derive_service import DeriveService
from voiceforge.domain.errors import (
    RenderFailed,
    ValidationError,
    VoiceNotFound,
)


def wav_bytes(rate: int = 44_100) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * 1000)
    return buffer.getvalue()


class FakePitch:
    def pitch(self, source, out_path, semitones):  # pragma: no cover - not used
        raise AssertionError("the pitch transform must not run for a timbre derive")


class FakeTimbre:
    def __init__(self, rate: int = 22_050, empty: bool = False) -> None:
        self.calls: list[tuple[Path, Path]] = []
        self.rate = rate
        self.empty = empty

    def timbre(self, source: Path, target_ref: Path, out_path: Path) -> None:
        self.calls.append((Path(source), Path(target_ref)))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"" if self.empty else wav_bytes(self.rate))


@pytest.fixture
def source_voice(catalog_service):
    return catalog_service.register(wav_bytes(), slug="alex", name="Alex")


@pytest.fixture
def target_voice(catalog_service):
    return catalog_service.register(
        wav_bytes(22_050), slug="narrador-terror", name="Narrador terror"
    )


@pytest.fixture
def timbre():
    return FakeTimbre()


@pytest.fixture
def service(repository, clock, timbre):
    return DeriveService(repository, FakePitch(), clock, timbre=timbre)


def test_timbre_derive_registers_provenance_and_the_new_rate(
    service, timbre, source_voice, target_voice, catalog_service
):
    derived = service.derive(
        "alex", slug="alex-hibrido", timbre_from="narrador-terror"
    )

    assert derived.slug == "alex-hibrido"
    assert derived.origin == "derived"
    assert derived.name == "Alex como Narrador terror"
    assert derived.language == source_voice.language
    assert derived.sample_rate == 22_050
    assert derived.reference_neutral is True
    assert dict(derived.recipe) == {
        "derived_from": "alex",
        "transform": "timbre",
        "timbre_from": "narrador-terror",
        "source_sha256": source_voice.ref_sha256,
        "timbre_sha256": target_voice.ref_sha256,
        "model": "tone-color-vc-f16",
    }
    assert timbre.calls == [
        (source_voice.ref_audio, target_voice.ref_audio),
    ]
    # Neither parent is modified.
    assert catalog_service.get("alex").ref_audio.exists()
    assert catalog_service.get("narrador-terror").ref_audio.exists()


def test_the_derived_voice_owns_its_clip_and_survives_both_parents(
    service, source_voice, target_voice, catalog_service, repository
):
    derived = service.derive(
        "alex", slug="alex-hibrido", timbre_from="narrador-terror"
    )
    clip = derived.ref_audio.read_bytes()

    catalog_service.remove("alex")
    catalog_service.remove("narrador-terror")

    survivor = repository.get("alex-hibrido")
    assert survivor.ref_audio.exists()
    assert survivor.ref_audio.read_bytes() == clip
    assert survivor.recipe["timbre_from"] == "narrador-terror"


def test_the_pitch_and_the_timbre_are_mutually_exclusive(service, source_voice, target_voice):
    with pytest.raises(ValidationError, match="not both"):
        service.derive(
            "alex",
            slug="alex-x",
            pitch_semitones=-2.0,
            timbre_from="narrador-terror",
        )


def test_a_derive_needs_one_transform(service, source_voice):
    with pytest.raises(ValidationError, match="pitch shift or a timbre source"):
        service.derive("alex", slug="alex-x")


def test_a_timbre_derive_without_the_converter_is_rejected(
    repository, clock, source_voice, target_voice
):
    service = DeriveService(repository, FakePitch(), clock)

    with pytest.raises(ValidationError, match="not configured"):
        service.derive("alex", slug="alex-x", timbre_from="narrador-terror")


def test_an_unknown_timbre_source_is_not_found(service, source_voice):
    with pytest.raises(VoiceNotFound):
        service.derive("alex", slug="alex-x", timbre_from="fantasma")


def test_an_empty_conversion_is_a_render_failure(
    repository, clock, source_voice, target_voice
):
    service = DeriveService(repository, FakePitch(), clock, timbre=FakeTimbre(empty=True))

    with pytest.raises(RenderFailed, match="produced no audio"):
        service.derive("alex", slug="alex-x", timbre_from="narrador-terror")


def test_the_default_pitch_is_still_the_documented_one(container, capsys):
    """No --timbre and no --pitch keeps the historical -2 semitones."""
    container.catalog.register(wav_bytes(), slug="cli-source", name="Cli source")
    args = build_parser().parse_args(["derive", "cli-source", "--slug", "cli-deep"])

    assert args.func(container, args) == 0
    output = capsys.readouterr().out

    voice = container.catalog.get("cli-deep")
    assert voice.recipe["transform"] == "pitch"
    assert voice.recipe["pitch_semitones"] == -2.0
    assert "-2.0 st" in output


def test_the_cli_timbre_derive_prints_the_target(container, capsys):
    container.catalog.register(wav_bytes(), slug="cli-source", name="Cli source")
    container.catalog.register(wav_bytes(), slug="cli-target", name="Cli target")
    args = build_parser().parse_args(
        ["derive", "cli-source", "--timbre", "cli-target", "--slug", "cli-hibrido"]
    )

    assert args.func(container, args) == 0
    output = capsys.readouterr().out

    voice = container.catalog.get("cli-hibrido")
    assert voice.recipe["transform"] == "timbre"
    assert voice.recipe["timbre_from"] == "cli-target"
    assert voice.sample_rate == 22_050
    assert "derived: cli-hibrido" in output
    assert "from cli-source" in output
    assert "timbre=cli-target" in output
    assert str(voice.ref_audio) in output
