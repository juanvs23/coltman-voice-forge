"""Narrate screen, no browser and no engine: validation, estimate and progress.

The render itself is exercised end to end elsewhere with fakes; here the
contract is that the generator never blocks without emitting the queue state,
that a broken script is one message instead of a traceback, and that the final
yield names the file and its duration.
"""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from voiceforge.adapters.primary.webui.context import UiContext
from voiceforge.adapters.primary.webui.narrate import (
    SECONDS_PER_LINE,
    dialogue_from_rows,
    estimate_dialogue,
    estimate_script,
    render_dialogue,
    render_script,
    resolved_out,
    validate_script,
)
from voiceforge.application.dialogue_service import DialogueService
from voiceforge.domain.errors import EngineUnavailable, ValidationError
from voiceforge.domain.models import EmotionAxis

TWO_LINES = """title: demo
lines:
  - voice: narrador
    text: "La casa llevaba veinte años vacía."
    pause_after_ms: 500
  - voice: narrador
    text: "Y aun así, alguien cerró la puerta."
    pause_after_ms: 900
"""

ONE_LINE = """title: demo
lines:
  - voice: narrador
    text: "La casa llevaba veinte años vacía."
    pause_after_ms: 0
"""


@pytest.fixture
def ctx(container) -> UiContext:
    return UiContext.from_container(container)


@pytest.fixture
def voice(container) -> str:
    container.catalog.register(b"RIFF-fake", slug="narrador", name="Narrador")
    return "narrador"


# ── validation ──────────────────────────────────────────────────────────
def test_validate_script_counts_the_lines():
    lines, error = validate_script(TWO_LINES)

    assert lines == 2
    assert error == ""


def test_validate_script_rejects_an_empty_line_list_without_a_traceback():
    lines, error = validate_script("title: demo\nlines: []\n")

    assert lines == 0
    assert "lines" in error
    assert "Traceback" not in error


def test_validate_script_rejects_broken_yaml():
    lines, error = validate_script("lines: [unclosed\n")

    assert lines == 0
    assert "YAML" in error


# ── line builder ────────────────────────────────────────────────────────
def _row(voice, text, preset="neutral", speed=1.0, pause=350):
    return (voice, text, preset, speed, pause)


def test_dialogue_from_rows_builds_lines_and_ignores_blank_rows():
    dialogue = dialogue_from_rows(
        [
            _row("narrador", "La casa llevaba veinte años vacía.", "tristeza", 1.2, 500),
            _row(None, ""),  # a visible row still waiting for text
            _row("clon", "  ", "miedo", 1.0, 900),  # whitespace is blank too
            _row("clon", "Y aun así, alguien cerró la puerta.", pause=700),
        ],
        "demo",
        0.4,
    )

    assert dialogue.title == "demo"
    assert [line.voice for line in dialogue.lines] == ["narrador", "clon"]
    first, second = dialogue.lines
    # The preset expands to the same axes a YAML script would name, and the
    # single global intensity lands on every line.
    assert first.emotion.axes[EmotionAxis.SAD] == pytest.approx(0.75)
    assert first.emotion.axes[EmotionAxis.MELANCHOLIC] == pytest.approx(0.35)
    assert first.emotion.intensity == pytest.approx(0.4)
    assert second.emotion.is_neutral
    assert second.emotion.intensity == pytest.approx(0.4)
    assert first.speed == pytest.approx(1.2)
    assert second.pause_after_ms == 700


def test_dialogue_from_rows_names_the_line_when_the_voice_is_missing():
    with pytest.raises(ValidationError, match="line 2: pick a voice"):
        dialogue_from_rows(
            [_row("narrador", "Uno."), _row(None, "Dos.")],
            "demo",
            0.6,
        )


def test_dialogue_from_rows_without_text_refuses_to_build_an_empty_dialogue():
    with pytest.raises(ValidationError, match="at least one line"):
        dialogue_from_rows([_row(None, ""), _row(None, "   ")], "demo", 0.6)


def test_dialogue_from_rows_falls_back_to_a_title():
    dialogue = dialogue_from_rows([_row("narrador", "Uno.")], "  ", 0.6)

    assert dialogue.title == "narración"
    assert dialogue.lines[0].emotion.intensity == pytest.approx(0.6)


# ── estimate ────────────────────────────────────────────────────────────
def test_estimate_uses_the_measured_rate_plus_the_pauses():
    lines, seconds, pauses_ms, message = estimate_script(TWO_LINES)

    assert lines == 2
    assert pauses_ms == 1400
    assert seconds == pytest.approx(2 * SECONDS_PER_LINE + 1.4)
    assert "Estimation" in message
    assert "not a promise" in message


def test_estimate_of_an_invalid_script_is_one_message():
    lines, seconds, pauses_ms, message = estimate_script("lines: []\n")

    assert (lines, seconds, pauses_ms) == (0, 0.0, 0)
    assert "rejected" in message
    assert "Traceback" not in message


def test_estimate_dialogue_counts_the_same_as_the_yaml_path():
    dialogue = dialogue_from_rows(
        [
            _row("narrador", "La casa llevaba veinte años vacía.", pause=500),
            _row("narrador", "Y aun así, alguien cerró la puerta.", pause=900),
        ],
        "demo",
        0.6,
    )

    from_lines = estimate_dialogue(dialogue)
    from_yaml = estimate_script(TWO_LINES)
    assert from_lines[:3] == from_yaml[:3]
    assert from_lines[0] == 2
    assert from_lines[2] == 1400
    assert "Estimation" in from_lines[3]
    assert "not a promise" in from_lines[3]


def test_resolved_out_defaults_to_out_narrate_wav(ctx):
    assert resolved_out(ctx, "") == ctx.settings.out_dir / "narrate.wav"
    assert resolved_out(ctx, None) == ctx.settings.out_dir / "narrate.wav"


# ── render ──────────────────────────────────────────────────────────────
def test_render_script_writes_the_default_file(ctx, container, voice):
    yields = list(render_script(ctx, ONE_LINE, "", False))

    target = container.settings.out_dir / "narrate.wav"
    assert target.is_file()
    assert len(yields) >= 1
    message, _ = yields[-1]
    assert str(target) in message
    assert "duration" in message
    assert "Traceback" not in message


def test_render_dialogue_writes_the_file_the_builder_describes(ctx, container, voice):
    dialogue = dialogue_from_rows(
        [_row(voice, "La casa llevaba veinte años vacía.", pause=0)],
        "demo",
        0.6,
    )

    yields = list(render_dialogue(ctx, dialogue, "", False))

    target = container.settings.out_dir / "narrate.wav"
    assert target.is_file()
    assert len(yields) >= 1
    message, _ = yields[-1]
    assert str(target) in message
    assert "duration" in message
    assert "Traceback" not in message


def test_render_script_with_a_broken_script_yields_exactly_one_error(ctx, voice):
    yields = list(render_script(ctx, "lines: []\n", "", False))

    assert len(yields) == 1
    assert "rejected" in yields[0][0]
    assert "Traceback" not in yields[0][0]


def test_render_script_reports_an_unwritable_path(ctx, voice, tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    yields = list(render_script(ctx, ONE_LINE, str(blocker / "narrate.wav"), False))

    assert len(yields) == 1
    assert "Cannot write" in yields[0][0]
    assert "Traceback" not in yields[0][0]


class _DownSynthesizer:
    """Fails the way a dead model host does, inside the queue job."""

    def synthesize(self, *, text, voice, emotion, speed, out_path):
        raise EngineUnavailable("model host did not answer /synthesize")


def test_render_script_engine_down_points_at_the_up_command(
    ctx, container, repository, assembler, tmp_path, voice
):
    dialogue = DialogueService(
        repository, _DownSynthesizer(), assembler, tmp_path / "work-down"
    )
    down = replace(ctx, dialogue=dialogue)

    yields = list(render_script(down, ONE_LINE, "", False))

    message, _ = yields[-1]
    assert "voice-forge up" in message
    assert "Traceback" not in message


class _BlockingSynthesizer:
    """Holds the job inside the queue until the gate opens."""

    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate

    def synthesize(self, *, text, voice, emotion, speed, out_path):
        self._gate.wait(5)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"RIFF-fake-line")
        return 1.0


def test_render_script_emits_the_queue_state_before_the_final_yield(
    ctx, container, repository, assembler, tmp_path, voice
):
    gate = threading.Event()
    dialogue = DialogueService(
        repository, _BlockingSynthesizer(gate), assembler, tmp_path / "work-progress"
    )
    streaming = replace(ctx, dialogue=dialogue)

    seen_busy = threading.Event()

    def release() -> None:
        # Another thread opens the gate, so the generator is the only consumer.
        seen_busy.wait(5)
        gate.set()

    threading.Thread(target=release, daemon=True).start()

    yields: list[tuple[str, str]] = []
    intermediate: tuple[str, str] | None = None
    for message, queue in render_script(streaming, ONE_LINE, "", False):
        yields.append((message, queue))
        if intermediate is None and ("busy" in queue or "running" in queue):
            intermediate = (message, queue)
            seen_busy.set()
        if len(yields) > 100:  # a safety valve, never expected to fire
            gate.set()
            break

    assert intermediate is not None
    assert intermediate[1].startswith("queue · busy")
    assert str(container.settings.out_dir / "narrate.wav") in yields[-1][0]


def test_render_dialogue_emits_the_queue_state_before_the_final_yield(
    ctx, container, repository, assembler, tmp_path, voice
):
    gate = threading.Event()
    dialogue_service = DialogueService(
        repository, _BlockingSynthesizer(gate), assembler, tmp_path / "work-builder"
    )
    streaming = replace(ctx, dialogue=dialogue_service)
    dialogue = dialogue_from_rows(
        [_row(voice, "La casa llevaba veinte años vacía.", pause=0)],
        "demo",
        0.6,
    )

    seen_busy = threading.Event()

    def release() -> None:
        seen_busy.wait(5)
        gate.set()

    threading.Thread(target=release, daemon=True).start()

    yields: list[tuple[str, str]] = []
    intermediate: tuple[str, str] | None = None
    for message, queue in render_dialogue(streaming, dialogue, "", False):
        yields.append((message, queue))
        if intermediate is None and ("busy" in queue or "running" in queue):
            intermediate = (message, queue)
            seen_busy.set()
        if len(yields) > 100:  # a safety valve, never expected to fire
            gate.set()
            break

    assert intermediate is not None
    assert intermediate[1].startswith("queue · busy")
    assert str(container.settings.out_dir / "narrate.wav") in yields[-1][0]
