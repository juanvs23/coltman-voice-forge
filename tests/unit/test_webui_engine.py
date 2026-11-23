"""Engine screen, no host: the status pair and the three mapped refusals.

The real lifecycle is covered against a live server elsewhere; here what must
hold is that every failure the control can raise becomes an operator sentence,
and that the queue line always comes from ``SerialQueue``.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from voiceforge.adapters.primary.webui.context import UiContext
from voiceforge.adapters.primary.webui.engine import run_action, status_report
from voiceforge.domain.errors import (
    EngineAlreadyRunning,
    EngineBusy,
    EngineUnavailable,
)


@pytest.fixture
def ctx(container) -> UiContext:
    return UiContext.from_container(container)


class _DownEngine:
    def status(self):
        return {"status": "down", "url": "http://127.0.0.1:8731"}

    def up(self):
        raise EngineUnavailable("server did not answer within 180s")

    def warm(self, modes=None):
        raise EngineUnavailable("server is down; run `voice-forge up` first")

    def down(self, *, force=False):
        return {"status": "down"}


class _RunningEngine:
    def status(self):
        return {"status": "up", "backend": "cuda", "url": "http://127.0.0.1:8731"}

    def up(self):
        raise EngineAlreadyRunning("the audio.cpp server is already running")

    def warm(self, modes=None):
        return {"warmed": True, "seconds": 2.4}

    def down(self, *, force=False):
        return {"status": "down"}


class _BusyEngine:
    def status(self):
        return {"status": "up", "backend": "cuda"}

    def up(self):
        return {"status": "up"}

    def warm(self, modes=None):
        return {"warmed": True}

    def down(self, *, force=False):
        raise EngineBusy("a job is running; wait for it or use `down --force`")


class _BrokenEngine:
    def status(self):
        raise RuntimeError("connection refused")

    def up(self):
        raise ValueError("not a lifecycle verb")

    def warm(self, modes=None):
        return {}

    def down(self, *, force=False):
        return {}


# ── status ──────────────────────────────────────────────────────────────
def test_status_report_pairs_the_host_with_the_queue(ctx):
    state, queue = status_report(ctx)

    assert "engine · up" in state
    assert f"adapter `{ctx.settings.adapter}`" in state
    assert f"device `{ctx.settings.device}`" in state
    assert f"model `{ctx.settings.model_path.name}`" in state
    assert queue.startswith("queue · idle")


def test_status_report_says_the_host_is_down(ctx):
    state, _ = status_report(replace(ctx, engine=_DownEngine()))

    assert "engine · down" in state
    assert "voice-forge up" in state


def test_status_report_survives_a_dead_probe(ctx):
    state, queue = status_report(replace(ctx, engine=_BrokenEngine()))

    assert "unreachable" in state
    assert "connection refused" in state
    assert queue.startswith("queue · idle")


def test_status_report_shows_missing_prerequisites(ctx):
    settings = replace(
        ctx.settings,
        adapter="audiocpp",
        transport="server",
        model_path=ctx.settings.out_dir / "missing.gguf",
    )
    state, _ = status_report(replace(ctx, settings=settings))

    assert "missing" in state
    assert "missing.gguf" in state


# ── actions ─────────────────────────────────────────────────────────────
def test_up_reports_success(ctx):
    state, _ = run_action(ctx, "up")

    assert "**Up**" in state
    assert "engine · up" in state


def test_up_on_a_live_host_reports_the_refusal(ctx):
    state, _ = run_action(replace(ctx, engine=_RunningEngine()), "up")

    assert "Up refused" in state
    assert "already running" in state
    assert "Traceback" not in state


def test_warm_reports_the_load_time(ctx):
    state, _ = run_action(replace(ctx, engine=_RunningEngine()), "warm")

    assert "**Warm**" in state
    assert "2.4 s" in state
    assert "engine · up" in state


def test_down_reports_the_stop(ctx):
    state, _ = run_action(replace(ctx, engine=_RunningEngine()), "down")

    assert "**Down**" in state


def test_up_on_a_dead_host_explains_the_boot_failure(ctx):
    state, _ = run_action(replace(ctx, engine=_DownEngine()), "up")

    assert "Up failed" in state
    assert "180s" in state
    assert "host log" in state
    assert "Traceback" not in state


def test_warm_on_a_dead_host_points_at_up(ctx):
    state, _ = run_action(replace(ctx, engine=_DownEngine()), "warm")

    assert "Warm failed" in state
    assert "voice-forge up" in state


def test_down_while_a_job_runs_reports_the_refusal(ctx):
    state, queue = run_action(replace(ctx, engine=_BusyEngine()), "down")

    assert "Down refused" in state
    assert "job is running" in state
    assert "--force" in state
    assert "Traceback" not in state
    assert queue.startswith("queue · idle")


def test_an_unexpected_error_is_still_a_sentence(ctx):
    state, _ = run_action(replace(ctx, engine=_BrokenEngine()), "up")

    assert "Up failed" in state
    assert "ValueError" in state
    assert "unreachable" in state  # the status probe is still attempted
    assert "Traceback" not in state


def test_an_unknown_action_is_reported(ctx):
    state, _ = run_action(ctx, "explode")

    assert "Unknown action" in state
    assert "explode" in state
