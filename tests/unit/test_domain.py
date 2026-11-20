from __future__ import annotations

import pytest

from voiceforge.domain.errors import ValidationError
from voiceforge.domain.models import Dialogue, Emotion, EmotionAxis, Line, VoiceBrief
from voiceforge.domain.script import parse_dialogue


def test_slug_rules_live_in_the_domain():
    from voiceforge.domain.models import Voice

    with pytest.raises(ValidationError):
        Voice(slug="With Spaces", name="x", ref_audio=None, language="es",
              sample_rate=1, recipe={}, created_at="now")
    with pytest.raises(ValidationError):
        Voice(slug="a", name="x", ref_audio=None, language="es",
              sample_rate=1, recipe={}, created_at="now")


def test_emotion_rejects_out_of_range_values():
    with pytest.raises(ValidationError):
        Emotion(axes={EmotionAxis.AFRAID: 1.5})
    with pytest.raises(ValidationError):
        Emotion(intensity=1.2)


def test_emotion_dominant_axis():
    emotion = Emotion(axes={EmotionAxis.AFRAID: 0.7, EmotionAxis.CALM: 0.2})
    assert emotion.dominant() is EmotionAxis.AFRAID
    assert emotion.is_neutral is False


def test_brief_limits_candidates():
    with pytest.raises(ValidationError):
        VoiceBrief(description="x", candidates=0)
    with pytest.raises(ValidationError):
        VoiceBrief(description="x", candidates=99)


def test_line_rejects_impossible_speed():
    with pytest.raises(ValidationError):
        Line(voice="a", text="hola", speed=0.1)


def test_dialogue_needs_lines():
    with pytest.raises(ValidationError):
        Dialogue(title="x", lines=())


def test_parse_dialogue_full_mapping():
    data = {
        "title": "demo",
        "lines": [
            {"voice": "narrador", "text": "uno", "emotion": {"afraid": 0.7}, "speed": 0.9},
            {"voice": "otro", "text": "dos", "emotion": "susurrando"},
        ],
    }
    dialogue = parse_dialogue(data)
    assert dialogue.title == "demo"
    assert dialogue.speakers == ("narrador", "otro")
    assert dialogue.lines[0].emotion.axes[EmotionAxis.AFRAID] == 0.7
    assert dialogue.lines[1].emotion.hint == "susurrando"


def test_parse_dialogue_rejects_unknown_axis():
    with pytest.raises(ValidationError) as exc:
        parse_dialogue({"lines": [{"voice": "a", "text": "b", "emotion": {"furious": 0.9}}]})
    assert "unknown emotion axis" in str(exc.value)


def test_parse_dialogue_rejects_missing_fields():
    with pytest.raises(ValidationError):
        parse_dialogue({"lines": [{"text": "sin voz"}]})
    with pytest.raises(ValidationError):
        parse_dialogue({})
