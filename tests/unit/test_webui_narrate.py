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
    estimate_script,
    render_script,
    resolved_out,
    validate_script,
)
from voiceforge.application.dialogue_service import DialogueService
from voiceforge.domain.errors import EngineUnavailable

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
