"""Preview screen, no browser and no engine: takes, rotation and slots.

The real GPU path is covered end to end elsewhere; here the queue, the pure
handlers and the three-slot rotation are what must hold.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from voiceforge.adapters.primary.webui.context import UiContext
from voiceforge.adapters.primary.webui.preview import (
    EMOTION_AXES,
    axes_from,
    preview_once,
    slots_html,
    slots_payload,
)
from voiceforge.application.preview_service import SLOTS
from voiceforge.domain.errors import EngineUnavailable


@pytest.fixture
def ctx(container) -> UiContext:
    return UiContext.from_container(container)


@pytest.fixture
def voice(container) -> str:
    container.catalog.register(b"RIFF-fake", slug="narrador", name="Narrador")
    return "narrador"


def _previews(container) -> Path:
    return container.settings.out_dir / "previews"


# ── one take ────────────────────────────────────────────────────────────
def test_preview_once_writes_a_take_and_fills_the_slot(ctx, container, voice):
    path, message, slots = preview_once(
        ctx, voice, "La casa estaba vacía.", {"melancholic": 0.4}, 0.6, 1.0, None
    )

    assert path is not None
    assert Path(path).is_file()
    assert "slot 0" in message
    assert "Traceback" not in message
    assert "/previews/slot-0.wav" in slots
    assert "La casa estaba vacía." in slots
    assert "melancholic=0.40" in slots


def test_four_takes_leave_exactly_three_slots(ctx, container, voice):
    for index in range(4):
        path, message, _ = preview_once(
            ctx, voice, f"toma {index}", {}, 0.6, 1.0, None
        )
        assert path is not None
        assert "Traceback" not in message

    previews = _previews(container)
    assert len(list(previews.glob("slot-*.wav"))) == SLOTS
    assert len(list(previews.glob("slot-*.json"))) == SLOTS


def test_preview_once_without_a_voice_returns_no_path(ctx):
    path, message, slots = preview_once(ctx, None, "hola", {}, 0.6, 1.0, None)

    assert path is None
    assert "Pick a voice" in message
    assert "empty" in slots


def test_preview_once_without_text_returns_no_path(ctx, voice):
    path, message, _ = preview_once(ctx, voice, "   ", {}, 0.6, 1.0, None)

    assert path is None
    assert "text" in message.lower()


def test_intensity_out_of_range_is_a_message_not_a_crash(ctx, voice):
    path, message, _ = preview_once(ctx, voice, "hola", {}, 1.5, 1.0, None)

    assert path is None
    assert "intensity" in message
    assert "Traceback" not in message


def test_unknown_axis_is_a_message_not_a_crash(ctx, voice):
    path, message, _ = preview_once(ctx, voice, "hola", {"furious": 0.7}, 0.6, 1.0, None)

    assert path is None
    assert "furious" in message
    assert "Traceback" not in message


# ── engine down ─────────────────────────────────────────────────────────
class _DownPreview:
    """Stands in for PreviewService: the job fails the way a dead host does."""

    def preview(self, slug, text, *, emotion=None, speed=1.0):
        raise EngineUnavailable("model host at http://127.0.0.1:8710 did not answer /synthesize")


def test_engine_down_is_an_operator_message(ctx, voice):
    down = replace(ctx, preview=_DownPreview())

    path, message, slots = preview_once(down, voice, "hola", {}, 0.6, 1.0, None)

    assert path is None
    assert "voice-forge up" in message
    assert "Traceback" not in message
    assert "empty" in slots


# ── axes ────────────────────────────────────────────────────────────────
def test_axes_from_maps_sliders_in_axis_order():
    values = [index / 10 for index in range(len(EMOTION_AXES))]

    axes = axes_from(values)

    assert list(axes) == [axis.value for axis in EMOTION_AXES]
    assert axes["happy"] == 0.0
    assert axes["calm"] == pytest.approx(0.7)


def test_emotion_axes_are_the_eight_domain_axes():
    assert [axis.value for axis in EMOTION_AXES] == [
        "happy",
        "angry",
        "sad",
        "afraid",
        "disgusted",
        "melancholic",
        "surprised",
        "calm",
    ]


# ── slots ───────────────────────────────────────────────────────────────
def test_empty_slots_say_so(ctx):
    markup = slots_html(ctx)

    assert markup.count("vf-slot-empty") == 3
    assert "/previews/slot-0.wav" not in markup


def test_slots_payload_always_returns_three_entries(ctx):
    payload = slots_payload(ctx)

    assert [entry["slot"] for entry in payload] == [0, 1, 2]
    assert all(entry == {"slot": entry["slot"], "empty": True} for entry in payload)


def test_slots_payload_reads_what_preview_once_wrote(ctx, voice):
    preview_once(ctx, voice, "La casa estaba vacía.", {"calm": 0.5}, 0.6, 1.0, None)

    payload = slots_payload(ctx)

    assert len(payload) == SLOTS
    assert payload[0]["empty"] is False
    assert payload[0]["voice"] == voice
    assert payload[0]["url"] == "/previews/slot-0.wav"
    assert payload[0]["axes"] == {"calm": 0.5}
