"""Design screen, no browser and no engine: audition, players, register.

The audition is what the API's two endpoints do, split in two: the candidates
land in ``out/candidates`` and the token is the only thing carried between the
steps. ``register_choice`` must therefore write exactly the ``voice.json`` the
one-call ``design`` path writes — that equivalence is the point of this file.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from voiceforge.adapters.primary.webui.context import UiContext
from voiceforge.adapters.primary.webui.design import (
    candidates_html,
    design_candidates,
    register_choice,
)
from voiceforge.application.catalog_service import CatalogService
from voiceforge.domain.errors import EngineUnavailable, VoiceNotFound
from voiceforge.domain.models import VoiceBrief

DESCRIPTION = "narrador grave y pausado"


@pytest.fixture
def ctx(container) -> UiContext:
    return UiContext.from_container(container)


def _auditions(container) -> Path:
    return container.settings.out_dir / "candidates"


def _payload(container, slug: str) -> dict:
    path = container.settings.catalog_dir / slug / "voice.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ── audition ────────────────────────────────────────────────────────────
def test_design_candidates_writes_n_wavs_and_a_sidecar(ctx, container):
    message, state, markup = design_candidates(
        ctx, DESCRIPTION, "Spanish", 3, 7, "La casa estaba vacía.", False
    )

    token = state["token"]
    assert re.fullmatch(r"[0-9a-f]{12}", token)
    directory = _auditions(container)
    assert len(list(directory.glob(f"{token}-*.wav"))) == 3

    sidecar = json.loads((directory / f"{token}.json").read_text(encoding="utf-8"))
    assert sidecar["token"] == token
    assert sidecar["brief"] == {
        "description": DESCRIPTION,
        "language": "Spanish",
        "seed": 7,
        "preview_text": "La casa estaba vacía.",
        "emotional": False,
    }
    assert [entry["index"] for entry in sidecar["candidates"]] == [0, 1, 2]
    assert [entry["sample_rate"] for entry in sidecar["candidates"]] == [24_000] * 3

    assert [entry["index"] for entry in state["candidates"]] == [0, 1, 2]
    assert state["candidates"][0]["url"] == f"/candidates/{token}-0.wav"
    assert markup.count("<audio") == 3
    assert "candidate 2" in markup
    assert "fake-designer" in markup
    assert "3 candidates" in message
    assert "Traceback" not in message


def test_a_second_audition_deletes_the_first(ctx, container):
    _, first, _ = design_candidates(ctx, DESCRIPTION, "Spanish", 2, None, None, False)
    _, second, _ = design_candidates(ctx, DESCRIPTION, "Spanish", 2, None, None, False)

    directory = _auditions(container)
    files = sorted(path.name for path in directory.iterdir())
    assert files == sorted(
        [f"{second['token']}-0.wav", f"{second['token']}-1.wav", f"{second['token']}.json"]
    )
    assert not (directory / f"{first['token']}-0.wav").exists()


def test_an_empty_description_asks_for_one(ctx):
    message, state, markup = design_candidates(ctx, "  ", "Spanish", 2, None, None, False)

    assert state == {}
    assert "description" in message.lower()
    assert "empty" in markup


def test_the_candidate_count_outside_the_domain_range_is_a_message(ctx):
    message, state, _ = design_candidates(ctx, DESCRIPTION, "Spanish", 99, None, None, False)

    assert state == {}
    assert "candidates must be within 1..8" in message
    assert "Traceback" not in message


# ── register ────────────────────────────────────────────────────────────
def test_register_choice_writes_the_same_voice_json_as_design(ctx, container):
    brief = VoiceBrief(
        description=DESCRIPTION,
        language="Spanish",
        candidates=3,
        seed=11,
        preview_text="La casa estaba vacía.",
    )
    container.catalog.design(
        brief, slug="via-design", name="Via Design", tags=("demo", "neutral")
    )
    _, state, _ = design_candidates(
        ctx,
        brief.description,
        brief.language,
        brief.candidates,
        brief.seed,
        brief.preview_text,
        False,
    )

    message, cards = register_choice(
        ctx, state, 0, "via-console", "Via Console", "demo, neutral", False
    )

    assert "Traceback" not in message
    assert "via-console" in message
    assert "via-console" in cards

    from_design = _payload(container, "via-design")
    from_console = _payload(container, "via-console")
    assert from_design["recipe"] == from_console["recipe"]
    for payload in (from_design, from_console):
        payload.pop("slug")
        payload.pop("name")
    assert from_design == from_console


def test_register_choice_takes_the_recipe_from_the_server_side(ctx, container):
    _, state, _ = design_candidates(ctx, DESCRIPTION, "Spanish", 2, None, None, False)

    register_choice(ctx, state, 1, "elegida", None, None, False)

    voice = container.catalog.get("elegida")
    assert voice.origin == "designed"
    assert voice.sample_rate == 24_000
    assert voice.recipe["picked"] == 1
    assert voice.recipe["candidates"] == 2
    assert voice.recipe["brief"] == DESCRIPTION
    assert voice.recipe["instruct"] == DESCRIPTION


def test_an_emotional_word_without_consent_names_the_word(ctx, container):
    # Auditioned with consent, registered without it: the register step is the
    # last gate, and it must say which word tripped it.
    _, state, _ = design_candidates(
        ctx, "una narradora triste y serena", "Spanish", 2, None, None, True
    )
    assert state["token"]

    message, _ = register_choice(ctx, state, 0, "triste-voz", None, None, False)

    assert "triste" in message
    assert "neutral" in message
    assert "Traceback" not in message
    with pytest.raises(VoiceNotFound):
        container.catalog.get("triste-voz")


def test_register_without_an_audition_asks_for_one(ctx):
    message, _ = register_choice(ctx, {}, 0, "ghost", None, None, False)

    assert "Generate candidates first" in message


def test_register_with_a_pick_outside_the_audition_is_a_message(ctx, container):
    _, state, _ = design_candidates(ctx, DESCRIPTION, "Spanish", 2, None, None, False)

    message, _ = register_choice(ctx, state, 9, "too-far", None, None, False)

    assert "within 0..1" in message
    with pytest.raises(VoiceNotFound):
        container.catalog.get("too-far")


def test_register_with_a_vanished_audition_is_a_message(ctx, container):
    _, state, _ = design_candidates(ctx, DESCRIPTION, "Spanish", 2, None, None, False)
    for stale in _auditions(container).iterdir():
        stale.unlink()

    message, _ = register_choice(ctx, state, 0, "ghost", None, None, False)

    assert "gone" in message
    assert "Traceback" not in message


# ── engine down ─────────────────────────────────────────────────────────
class _DownDesigner:
    """The designer as a dead host presents it: a model call that cannot run."""

    def design(self, brief):
        raise EngineUnavailable(
            "model host at http://127.0.0.1:8731 did not answer /v1/audio/speech"
        )


def test_engine_down_is_an_operator_message(ctx, repository, clock):
    down = replace(ctx, catalog=CatalogService(repository, _DownDesigner(), clock))

    message, state, markup = design_candidates(
        down, DESCRIPTION, "Spanish", 2, None, None, False
    )

    assert "voice-forge up" in message
    assert "Traceback" not in message
    assert state == {}
    assert "No candidates yet" in markup


# ── players ─────────────────────────────────────────────────────────────
def test_candidates_html_escapes_content_and_counts_players():
    markup = candidates_html(
        [
            {
                "index": 0,
                "url": "/candidates/abc-0.wav",
                "sample_rate": 24_000,
                "recipe": {"instruct": "<script>alert(1)</script>"},
            }
        ]
    )

    assert markup.count("<audio") == 1
    assert 'src="/candidates/abc-0.wav"' in markup
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
