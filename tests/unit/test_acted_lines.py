"""Acted lines: a ``source:`` take converted to the line's voice.

No GPU and no models: the converter is the shared fake, which writes a real
22,050 Hz wav so the duration really comes from a file.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from voiceforge.application.dialogue_service import DialogueService
from voiceforge.domain.errors import ValidationError
from voiceforge.domain.models import Dialogue, Line, Voice
from voiceforge.domain.script import load_dialogue, parse_dialogue


def _write_wav(path: Path, *, rate: int = 22_050, frames: int = 22_050) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)
    return path


def _duration_of(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def _safe_duration(path: Path) -> float:
    """Synthetic fakes may write placeholder bytes; the acted take is a real wav."""
    try:
        return _duration_of(path)
    except (wave.Error, EOFError):
        return 0.0


def _voice(slug: str, ref: Path) -> Voice:
    return Voice(
        slug=slug,
        name=slug.title(),
        ref_audio=ref,
        language="Spanish",
        sample_rate=44_100,
        recipe={"model": "fake"},
        created_at="2026-11-23T00:00:00+00:00",
    )


class StubCatalog:
    def __init__(self, voices: dict[str, Voice]) -> None:
        self.voices = voices

    def get(self, slug: str) -> Voice:
        return self.voices[slug]


class WaveSynthesizer:
    """Writes a real wav, so every segment's duration can be read back."""

    def __init__(self, seconds: float = 1.0, rate: int = 44_100) -> None:
        self.seconds = seconds
        self.rate = rate
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, *, text, voice, emotion, speed, out_path):
        self.calls.append((text, voice.slug))
        _write_wav(
            Path(out_path), rate=self.rate, frames=int(self.seconds * self.rate)
        )
        return self.seconds


class RecordingAssembler:
    """Records the segments while their temp files still exist."""

    def __init__(self) -> None:
        self.segments: list[tuple[Path, int, float]] = []

    def assemble(self, segments, out_path, target_lufs):
        self.segments = [
            (Path(path), pause, _safe_duration(Path(path))) for path, pause in segments
        ]
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"RIFF-fake-mix")
        return out_path, sum(duration for _, _, duration in self.segments)

    def measure_lufs(self, path):
        return -14.0


# ── parsing ─────────────────────────────────────────────────────────────
def test_a_source_line_parses_without_text():
    dialogue = parse_dialogue(
        {"lines": [{"voice": "narrador", "source": "takes/linea.wav"}]}
    )
    line = dialogue.lines[0]
    assert line.source == "takes/linea.wav"
    assert line.text is None
    assert dialogue.base_dir is None


def test_text_and_source_together_name_the_line_and_the_fields():
    with pytest.raises(ValidationError) as error:
        parse_dialogue(
            {"lines": [{"voice": "narrador", "text": "hola", "source": "take.wav"}]}
        )
    message = str(error.value)
    assert "line 1" in message
    assert "text" in message and "source" in message


def test_a_line_with_neither_text_nor_source_is_rejected():
    with pytest.raises(ValidationError) as error:
        parse_dialogue({"lines": [{"voice": "narrador"}]})
    message = str(error.value)
    assert "line 1" in message
    assert "text" in message and "source" in message


def test_the_model_refuses_an_invalid_line_directly():
    with pytest.raises(ValidationError):
        Line(voice="narrador")
    with pytest.raises(ValidationError):
        Line(voice="narrador", text="hola", source="take.wav")


# ── resolution and rendering ────────────────────────────────────────────
def test_relative_source_resolves_against_the_script_folder(tmp_path, timbre, synthesizer):
    take = _write_wav(tmp_path / "takes" / "linea.wav")
    script = tmp_path / "guion.yaml"
    script.write_text(
        "title: actuado\n"
        "lines:\n"
        "  - voice: narrador\n"
        "    source: takes/linea.wav\n",
        encoding="utf-8",
    )
    dialogue = load_dialogue(script)
    assert dialogue.base_dir == tmp_path

    assembler = RecordingAssembler()
    service = DialogueService(
        StubCatalog({"narrador": _voice("narrador", tmp_path / "narrador.wav")}),
        synthesizer,
        assembler,
        tmp_path / "work",
        timbre=timbre,
    )
    service.render(dialogue, tmp_path / "out.wav", target_lufs=None)

    assert len(timbre.calls) == 1
    assert timbre.calls[0][0] == take.resolve()


def test_mixed_render_converts_once_and_reads_duration_from_the_file(tmp_path, timbre):
    timbre.frames = 22_050  # a real one-second produced wav
    take = _write_wav(tmp_path / "take.wav", frames=44_100)  # the acted source
    voices = {
        "alex": _voice("alex", tmp_path / "alex.wav"),
        "narrador": _voice("narrador", tmp_path / "narrador.wav"),
    }
    dialogue = Dialogue(
        title="mixto",
        lines=(
            Line(voice="alex", text="La puerta se abrió."),
            Line(voice="narrador", source=str(take), pause_after_ms=0),
        ),
    )

    synthesizer = WaveSynthesizer(seconds=1.0)
    assembler = RecordingAssembler()
    service = DialogueService(
        StubCatalog(voices), synthesizer, assembler, tmp_path / "work", timbre=timbre
    )
    result = service.render(dialogue, tmp_path / "mixto.wav", target_lufs=None)

    # One conversion, for the acted line only, into that line's voice.
    assert len(timbre.calls) == 1
    source, target_ref, produced = timbre.calls[0]
    assert source == take.resolve()
    assert target_ref == voices["narrador"].ref_audio
    assert produced.name == "line-0001.wav"
    # The synthetic line was synthesised, never converted.
    assert len(synthesizer.calls) == 1

    # The converted segment is the file the converter wrote, and its duration
    # comes from that file — the fake's ``timbre`` returns nothing.
    converted_path, pause, converted_duration = assembler.segments[1]
    assert converted_path == produced
    assert pause == 0
    assert converted_duration == pytest.approx(1.0)

    # Total = the synthetic line's reported duration + the produced wav's.
    assert result.duration_s == pytest.approx(1.0 + 1.0)
    assert result.lines == 2
    assert (tmp_path / "mixto.wav").exists()


def test_acted_line_without_a_converter_is_rejected(tmp_path, synthesizer):
    take = _write_wav(tmp_path / "take.wav")
    dialogue = Dialogue(
        title="sin conversor",
        lines=(Line(voice="narrador", source=str(take)),),
    )
    service = DialogueService(
        StubCatalog({"narrador": _voice("narrador", tmp_path / "n.wav")}),
        synthesizer,
        RecordingAssembler(),
        tmp_path / "work",
    )
    with pytest.raises(ValidationError) as error:
        service.render(dialogue, tmp_path / "out.wav", target_lufs=None)
    assert "no converter is configured" in str(error.value)


def test_missing_source_is_rejected_with_its_resolved_path(tmp_path, timbre, synthesizer):
    missing = (tmp_path / "nope.wav").resolve()
    dialogue = Dialogue(
        title="falta",
        lines=(Line(voice="narrador", source="nope.wav"),),
        base_dir=tmp_path,
    )
    service = DialogueService(
        StubCatalog({"narrador": _voice("narrador", tmp_path / "n.wav")}),
        synthesizer,
        RecordingAssembler(),
        tmp_path / "work",
        timbre=timbre,
    )
    with pytest.raises(ValidationError) as error:
        service.render(dialogue, tmp_path / "out.wav", target_lufs=None)
    assert str(missing) in str(error.value)
