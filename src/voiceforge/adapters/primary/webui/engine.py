"""Engine screen: the host's real state and the three lifecycle actions.

Nothing here probes anything on import: ``build_console`` paints "not probed"
and only a click asks the host. Errors are translated into operator sentences —
a traceback never reaches the page — and the queue line comes from
``SerialQueue``, the only planner in the system.
"""

from __future__ import annotations

from typing import Mapping

from ....domain.errors import (
    EngineAlreadyRunning,
    EngineBusy,
    EngineUnavailable,
    VoiceForgeError,
)
from .context import UiContext, engine_line, engine_prerequisites, queue_line

ACTIONS = ("up", "warm", "down")


# ── state ───────────────────────────────────────────────────────────────
def status_report(ctx: UiContext) -> tuple[str, str]:
    """Readable state and queue: the pair the Engine tab shows."""
    snapshot: dict
    try:
        snapshot = dict(ctx.engine.status())  # EngineControl.status
    except Exception as exc:  # noqa: BLE001 - a dead host must not break the page
        return f"engine · unreachable · {exc}", queue_line(ctx.queue.snapshot())

    settings = ctx.settings
    backend = snapshot.get("backend") or snapshot.get("device") or settings.device
    lines = [
        engine_line(snapshot),
        f"adapter `{settings.adapter}` · device `{backend}` · "
        f"model `{settings.model_path.name}`",
    ]
    if snapshot.get("url"):
        lines.append(f"endpoint `{snapshot['url']}`")
    missing = engine_prerequisites(ctx)
    if missing:
        lines.append("> cannot start yet — " + "; ".join(missing))
    return "\n\n".join(lines), queue_line(ctx.queue.snapshot())


# ── actions ─────────────────────────────────────────────────────────────
def run_action(ctx: UiContext, action: str | None) -> tuple[str, str]:
    """Run ``up``/``warm``/``down`` and report what happened.

    Returns the fresh state (with the outcome as its first line) and the queue
    line, so one click updates both halves of the screen.
    """
    name = (action or "").strip().lower()
    if name not in ACTIONS:
        state, queue = status_report(ctx)
        return f"**Unknown action** `{name}` — use up, warm or down.\n\n{state}", queue

    try:
        result = dict(_perform(ctx, name) or {})
        note = _success_note(name, result)
    except EngineAlreadyRunning as exc:
        note = (
            f"**Up refused** — {exc}. One host instance only; the running one "
            "answers on the endpoint below."
        )
    except EngineBusy as exc:
        note = (
            f"**Down refused** — {exc}. A job is still running: wait for the "
            "queue to drain, or discard it from a terminal with "
            "`voice-forge down --force`."
        )
    except EngineUnavailable as exc:
        if name == "up":
            note = (
                f"**Up failed** — {exc}. Check the missing paths below and the "
                "host log before trying again."
            )
        elif name == "warm":
            note = f"**Warm failed** — {exc}. Run `voice-forge up` first."
        else:
            note = f"**Down failed** — {exc} No signal was sent."
    except (VoiceForgeError, OSError) as exc:
        note = f"**{name.capitalize()} failed** — {exc}"
    except Exception as exc:  # noqa: BLE001 - the page reports, it never crashes
        note = f"**{name.capitalize()} failed** — {type(exc).__name__}: {exc}"

    state, queue = status_report(ctx)
    return f"{note}\n\n{state}", queue


def _perform(ctx: UiContext, action: str) -> Mapping[str, object]:
    if action == "up":
        return ctx.engine.up()
    if action == "warm":
        return ctx.engine.warm()
    # No `force`: the console never discards work, it reports the refusal.
    return ctx.engine.down()


def _success_note(action: str, result: Mapping[str, object]) -> str:
    if action == "up":
        pid = result.get("pid")
        return f"**Up** — the model host answered{f' (pid {pid})' if pid else ''}."
    if action == "warm":
        if result.get("warmed"):
            seconds = result.get("seconds")
            suffix = f" in {seconds} s" if seconds is not None else ""
            return f"**Warm** — the model answered{suffix}."
        loaded = result.get("loaded")
        if loaded:
            return f"**Warm** — loaded {', '.join(str(mode) for mode in loaded)}."
        return "**Warm** — the host accepted the request."
    via = result.get("via")
    return f"**Down** — the host stopped{f' (via {via})' if via else ''}."
