"""The audio.cpp CLI adapter: command shape and instruction composition.

No binary, no model, no GPU: the runner is injected and writes a real wav.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from voiceforge.adapters.secondary.audiocpp_cli import AudiocppCli, build_instruct
from voiceforge.domain.errors import ValidationError
from voiceforge.domain.models import Emotion, EmotionAxis, VoiceBrief


def _write_wav(path: Path, seconds: float = 0.5, rate: int = 44_100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))


class RecordingRunner:
    def __init__(self, seconds: float = 0.5):
        self.commands: list[list[str]] = []
        self.seconds = seconds

    def __call__(self, command, timeout):
        self.commands.append(list(command))
        out = None
        for index, token in enumerate(command):
            if token == "--out":
                out = Path(command[index + 1])
        if out is not None:
            _write_wav(out, self.seconds)
        return 0, ""


@pytest.fixture
def adapter(tmp_path) -> tuple[AudiocppCli, RecordingRunner]:
    runner = RecordingRunner()
    binary = tmp_path / "audiocpp_cli"
    binary.write_text("#!/bin/sh\n")
    model = tmp_path / "ming.gguf"
    model.write_bytes(b"gguf")
    return AudiocppCli(binary=binary, model=model, backend="cpu", runner=runner), runner


# ── instruction composition (pure) ──────────────────────────────────────
def test_neutral_emotion_yields_no_instruction():
    assert build_instruct(Emotion()) is None


def test_axes_become_short_spanish_words():
    text = build_instruct(Emotion(axes={EmotionAxis.AFRAID: 0.8, EmotionAxis.CALM: 0.5}))
    assert text is not None
    assert "intensamente aterrado" in text
    assert "claramente sereno" in text


def test_speed_and_hint_are_appended():
    text = build_instruct(Emotion(hint="con la respiración entrecortada"), speed=0.8)
    assert text is not None
    assert "ritmo lento" in text
    assert "respiración" in text


# ── voice design ────────────────────────────────────────────────────────
def test_design_runs_vdes_once_per_candidate(adapter, tmp_path):
    client, runner = adapter
    brief = VoiceBrief(description="narrador grave", candidates=3, seed=100)

    candidates = client.design(brief)

    assert len(candidates) == 3
    assert all(candidate.audio[:4] == b"RIFF" for candidate in candidates)
    assert [candidate.recipe["seed"] for candidate in candidates] == [100, 101, 102]
    assert all(command[command.index("--task") + 1] == "vdes" for command in runner.commands)
    assert all("--family" in command and "ming3_tts" in command for command in runner.commands)
    assert len(runner.commands) == 3


def test_design_maps_the_language_and_rejects_unknown(adapter):
    client, _ = adapter
    client.design(VoiceBrief(description="x", language="Spanish", candidates=1))
    with pytest.raises(ValidationError):
        client.design(VoiceBrief(description="x", language="Klingon", candidates=1))


# ── synthesis ───────────────────────────────────────────────────────────
def _voice(tmp_path) -> "object":
    from voiceforge.domain.models import Voice

    ref = tmp_path / "ref.wav"
    _write_wav(ref, 1.0)
    return Voice(
        slug="narrador",
        name="Narrador",
        ref_audio=ref,
        language="Spanish",
        sample_rate=44_100,
        recipe={"seed": 1895},
        created_at="2026-11-20T00:00:00+00:00",
        ref_transcript="La casa estaba vacía.",
        ref_sha256="x" * 64,
    )


def test_synthesize_clones_with_freeform_and_reference_text(adapter, tmp_path):
    client, runner = adapter
    voice = _voice(tmp_path)
    out = tmp_path / "line.wav"

    duration = client.synthesize(
        text="Entra.",
        voice=voice,
        emotion=Emotion(axes={EmotionAxis.AFRAID: 0.8}),
        speed=1.0,
        out_path=out,
    )

    assert out.exists()
    assert duration == pytest.approx(0.5, abs=0.01)
    command = runner.commands[0]
    assert command[command.index("--task") + 1] == "clon"
    assert str(voice.ref_audio) in command
    assert "template_name=freeform" in command
    assert any(token.startswith("instruct=") for token in command)
    assert not any(token.startswith("reference_text=") for token in command)
    assert "seed=1895" in command


def test_synthesize_without_emotion_uses_the_plain_template(adapter, tmp_path):
    client, runner = adapter
    voice = _voice(tmp_path)

    client.synthesize(
        text="Entra.",
        voice=voice,
        emotion=Emotion(),
        speed=1.0,
        out_path=tmp_path / "line.wav",
    )

    command = runner.commands[0]
    assert not any(token.startswith("template_name=") for token in command)


def test_speed_alone_becomes_words_not_a_slot(adapter, tmp_path):
    client, runner = adapter
    voice = _voice(tmp_path)

    client.synthesize(
        text="Entra.",
        voice=voice,
        emotion=Emotion(),
        speed=0.8,
        out_path=tmp_path / "line.wav",
    )

    command = runner.commands[0]
    assert "template_name=freeform" in command
    assert any("ritmo lento" in token for token in command)
