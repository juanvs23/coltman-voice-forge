from __future__ import annotations

import pytest

from voiceforge.domain.errors import ValidationError
from voiceforge.domain.models import Dialogue, Emotion, EmotionAxis, Line, VoiceBrief


@pytest.fixture
def script(catalog_service):
    catalog_service.design(VoiceBrief(description="narrador"), slug="narrador", name="Narrador")
    catalog_service.design(VoiceBrief(description="personaje"), slug="personaje", name="Personaje")
    return Dialogue(
        title="demo",
        lines=(
            Line(voice="narrador", text="La casa estaba vacía.", pause_after_ms=500),
            Line(
                voice="personaje",
                text="¿Hay alguien?",
                emotion=Emotion(axes={EmotionAxis.AFRAID: 0.7}, intensity=0.8),
                speed=0.9,
                pause_after_ms=0,
            ),
        ),
    )


def test_render_orders_lines_and_passes_emotion(dialogue_service, synthesizer, assembler, script, tmp_path):
    out = tmp_path / "out" / "narracion.wav"
    result = dialogue_service.render(script, out, target_lufs=-14.0)

    assert result.lines == 2
    assert result.speakers == ("narrador", "personaje")
    assert out.exists()

    texts = [call[0] for call in synthesizer.calls]
    assert texts == ["La casa estaba vacía.", "¿Hay alguien?"]

    emotions = [call[2] for call in synthesizer.calls]
    assert emotions[0].is_neutral
    assert emotions[1].axes[EmotionAxis.AFRAID] == 0.7
    assert synthesizer.calls[1][3] == 0.9

    segments, out_path, lufs = assembler.calls[0]
    assert out_path == out
    assert lufs == -14.0
    assert [pause for _, pause in segments] == [500, 0]


def test_render_fails_before_touching_the_gpu_on_unknown_voice(dialogue_service, synthesizer, script, tmp_path):
    broken = Dialogue(
        title="x",
        lines=(Line(voice="fantasma", text="hola"),),
    )
    with pytest.raises(ValidationError):
        dialogue_service.render(broken, tmp_path / "never.wav")
    assert synthesizer.calls == []


def test_render_without_mastering(dialogue_service, assembler, script, tmp_path):
    dialogue_service.render(script, tmp_path / "a.wav", target_lufs=None)
    assert assembler.calls[0][2] is None


def test_render_creates_missing_directories(dialogue_service, script, tmp_path):
    out = tmp_path / "deep" / "nested" / "x.wav"
    dialogue_service.render(script, out)
    assert out.exists()
