"""A catalog voice is a neutral identity. Emotion belongs to each line."""

from __future__ import annotations

import pytest

from voiceforge.domain.errors import ValidationError
from voiceforge.domain.models import VoiceBrief


def test_design_rejects_an_emotional_description(catalog_service):
    brief = VoiceBrief(description="hombre aterrado y triste, voz grave")
    with pytest.raises(ValidationError) as exc:
        catalog_service.design(brief, slug="voz")
    message = str(exc.value)
    assert "aterrado" in message and "triste" in message
    assert "--emotional" in message


def test_design_accepts_it_when_declared(catalog_service, catalog_dir):
    import json

    brief = VoiceBrief(description="hombre aterrado y triste, voz grave")
    voice, _ = catalog_service.design(brief, slug="voz", neutral=False)

    assert voice.reference_neutral is False
    payload = json.loads((catalog_dir / "voz" / "voice.json").read_text())
    assert payload["reference_neutral"] is False


def test_delivery_words_are_not_emotion(catalog_service):
    """Whispering and pace are style: a neutral narrator may use them."""
    brief = VoiceBrief(description="hombre de 60, voz rasposa, susurrante, ritmo lento")
    voice, _ = catalog_service.design(brief, slug="narrador")
    assert voice.reference_neutral is True


def test_register_checks_the_recipe_instruct(catalog_service):
    with pytest.raises(ValidationError):
        catalog_service.register(
            b"RIFF-x",
            slug="clon",
            name="Clon",
            recipe={"instruct": "voz enfadada y furiosa"},
        )


def test_register_accepts_a_neutral_instruct(catalog_service):
    voice = catalog_service.register(
        b"RIFF-x",
        slug="clon",
        name="Clon",
        recipe={"instruct": "mujer joven, voz suave, ritmo pausado"},
    )
    assert voice.reference_neutral is True


def test_the_flag_survives_a_reload(catalog_service):
    catalog_service.design(VoiceBrief(description="voz aterrada"), slug="voz-a", neutral=False)
    assert catalog_service.get("voz-a").reference_neutral is False
