"""What the operator console needs from the container, plus pure formatters.

The console is a client of the same API the CLI drives. It receives a
``UiContext`` built from the container — no module-level globals — so every
handler works on the wiring it was created with and ``create_app`` stays safe
to call twice in one process (which is exactly what the tests do).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ....application.audition_store import AuditionStore
from ....application.catalog_service import CatalogService
from ....application.derive_service import DeriveService
from ....application.dialogue_service import DialogueService
from ....application.preview_service import SLOTS, PreviewService
from ....application.queue import SerialQueue
from ....config import Settings
from ....container import Container
from ....domain.models import Voice


@dataclass(frozen=True)
class UiContext:
    """The container slice the console needs, resolved once per app."""

    catalog: CatalogService
    queue: SerialQueue
    engine: object  # EngineControl: status/up/warm/down, not a shared protocol yet
    preview: PreviewService
    derive: DeriveService
    dialogue: DialogueService
    auditions: AuditionStore
    settings: Settings

    @classmethod
    def from_container(cls, container: Container) -> "UiContext":
        return cls(
            catalog=container.catalog,
            queue=container.queue,
            engine=container.engine,
            preview=container.preview,
            derive=container.derive,
            dialogue=container.dialogue,
            # Same layout the API writes; derived from settings, so the console
            # and the endpoints cannot drift.
            auditions=AuditionStore(container.settings.out_dir),
            settings=container.settings,
        )


# ── catalog formatting ──────────────────────────────────────────────────
def origin_badge(voice: Voice) -> str:
    """One short label for where a voice came from."""
    if voice.origin == "derived":
        parent = voice.recipe.get("derived_from")
        return f"derived · {parent}" if parent else "derived"
    return voice.origin


RECIPE_KEYS = (
    "model",
    "instruct",
    "derived_from",
    "timbre_from",
    "pitch_semitones",
    "seed",
    "reference",
)


def recipe_text(recipe: Mapping[str, object] | None, limit: int = 120) -> str:
    """The interesting part of a raw recipe, never the whole blob."""
    recipe = dict(recipe or {})
    if not recipe:
        return "no recipe"
    keys = [key for key in RECIPE_KEYS if recipe.get(key) not in (None, "")]
    if not keys:
        keys = sorted(recipe)
    text = " · ".join(f"{key}={recipe[key]}" for key in keys)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def recipe_summary(voice: Voice, limit: int = 120) -> str:
    """The interesting part of a voice's recipe, never the whole blob."""
    return recipe_text(voice.recipe, limit)


# ── engine and queue formatting ─────────────────────────────────────────
def engine_line(status: Mapping[str, object] | None) -> str:
    """Readable one-liner for whatever ``engine.status()`` returned."""
    status = dict(status or {})
    state = str(status.get("status") or "unknown")
    if state == "up":
        detail = status.get("backend") or status.get("device")
        return f"engine · up · {detail}" if detail else "engine · up"
    if state == "down":
        return "engine · down · run `voice-forge up`"
    if state == "cli":
        return "engine · cli · model loads per call"
    return f"engine · {state}"


def queue_line(snapshot: Mapping[str, object]) -> str:
    """Depth of the serial queue, including work owned by another process."""
    pending = int(snapshot.get("pending") or 0)
    if snapshot.get("busy"):
        active = snapshot.get("running") or snapshot.get("active") or "another process"
        return f"queue · busy · {active} · {pending} pending"
    if pending:
        return f"queue · idle worker · {pending} pending"
    return "queue · idle"


def engine_prerequisites(ctx: UiContext) -> list[str]:
    """Local files the host needs. No network, no status probe."""
    settings = ctx.settings
    if settings.adapter == "qwen":
        candidates = [("engine script", settings.engine_script)]
    elif settings.transport == "server":
        candidates = [("server binary", settings.server_bin), ("model", settings.model_path)]
    else:
        candidates = [("runtime binary", settings.runtime_bin), ("model", settings.model_path)]
    return [
        f"{label} missing: `{path}`"
        for label, path in candidates
        if not path.is_file()
    ]


# ── preview slots ───────────────────────────────────────────────────────
def preview_slots(out_dir: Path) -> list[dict]:
    """The three fixed preview slots, always in order, empty ones included.

    The console and ``GET /api/previews`` read the same sidecars through this
    one function, so they cannot drift. A missing or corrupt sidecar degrades
    to an empty entry: the shape is constant whether the slots were ever used.
    """
    previews = Path(out_dir) / "previews"
    entries: list[dict] = []
    for slot in range(SLOTS):
        sidecar = previews / f"slot-{slot}.json"
        entry = {"slot": slot, "empty": True}
        if sidecar.is_file():
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            if isinstance(data, dict):
                entry = {
                    "slot": slot,
                    "empty": False,
                    "voice": data.get("voice"),
                    "text": data.get("text"),
                    "axes": data.get("axes") or {},
                    "intensity": data.get("intensity"),
                    "speed": data.get("speed"),
                    "duration_s": data.get("duration_s"),
                    "url": f"/previews/slot-{slot}.wav",
                }
        entries.append(entry)
    return entries
