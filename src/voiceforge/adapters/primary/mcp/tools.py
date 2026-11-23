"""MCP tools as pure functions.

Each function takes a ``VoiceForgeClient`` (or any object with the same
methods) and returns exactly what the API returned. Keeping them free of the
MCP SDK and of Gradio makes them testable against a fake client, and leaves the
protocol layer (``server.py``) with nothing but registration and docstrings.

Deliberately absent: any tool that deletes a catalog voice. An autonomous agent
must not delete the operator's data; destructive work stays in the CLI and in
the operator console, where a human is present.

Two guards make that posture real instead of aspirational:

* ``render_dialogue`` only writes inside the output directory and never inside
  ``catalog/``, so a hallucinated path cannot overwrite ``ref.wav``.
* ``clone_voice`` only reads an existing regular file and cannot choose a
  destination: the voice always lands in ``catalog/<slug>/``, and the API
  validates the slug.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ....config import Settings

ENGINE_ACTIONS = ("up", "warm", "down")


def _project_dirs() -> tuple[Path, Path]:
    """The output and catalog roots of this process, which owns the same repo."""
    settings = Settings()
    return (
        settings.out_dir.expanduser().resolve(),
        settings.catalog_dir.expanduser().resolve(),
    )


def resolve_render_out(
    out: str | None,
    *,
    out_dir: Path | None = None,
    catalog_dir: Path | None = None,
) -> str | None:
    """Return the absolute render destination, or refuse a dangerous one.

    ``None`` is left to the server (``out/render.wav``). Any other path must
    resolve under the output directory and must not resolve into ``catalog/``;
    ``resolve()`` is used so a symlink cannot smuggle a target past the check.
    """
    if out is None:
        return None

    if out_dir is None or catalog_dir is None:
        default_out, default_catalog = _project_dirs()
        out_dir = out_dir or default_out
        catalog_dir = catalog_dir or default_catalog

    out_root = Path(out_dir).expanduser().resolve()
    catalog_root = Path(catalog_dir).expanduser().resolve()
    target = Path(out).expanduser().resolve()

    if target.is_relative_to(catalog_root):
        raise ValueError(
            f"refusing to write into the catalog: {target} is inside {catalog_root}. "
            "The catalog is the operator's data and a voice reference must never be "
            f"overwritten. Choose a destination under {out_root}."
        )
    if target == out_root or not target.is_relative_to(out_root):
        raise ValueError(
            f"refusing to write outside the output directory: {target} is not a file "
            f"under {out_root}. Pass a path such as 'out/narration.wav', or omit 'out' "
            "and let the server choose."
        )
    return str(target)


def list_voices(client: Any) -> list[dict]:
    return client.list_voices()


def show_voice(client: Any, slug: str) -> dict:
    return client.show_voice(slug)


def preview_voice(
    client: Any,
    slug: str,
    text: str,
    axes: dict[str, float] | None = None,
    intensity: float = 0.6,
    speed: float = 1.0,
    hint: str | None = None,
) -> dict:
    return client.preview_voice(
        slug,
        text,
        axes=axes,
        intensity=intensity,
        speed=speed,
        hint=hint,
    )


def render_dialogue(
    client: Any, script: str, out: str | None = None, master: bool = True
) -> dict:
    target = resolve_render_out(out)
    return client.render_dialogue(script, out=target, master=master)


def design_candidates(
    client: Any,
    description: str,
    candidates: int = 4,
    language: str = "Spanish",
    seed: int | None = None,
    preview_text: str | None = None,
    emotional: bool = False,
) -> dict:
    return client.design_candidates(
        description,
        candidates=candidates,
        language=language,
        seed=seed,
        preview_text=preview_text,
        emotional=emotional,
    )


def register_candidate(
    client: Any,
    token: str,
    pick: int,
    slug: str,
    name: str | None = None,
    tags: list[str] | None = None,
    emotional: bool = False,
) -> dict:
    return client.register_candidate(
        token,
        pick,
        slug,
        name=name,
        tags=tags,
        emotional=emotional,
    )


def clone_voice(
    client: Any,
    audio_path: str,
    slug: str,
    name: str | None = None,
    language: str = "Spanish",
    transcript: str | None = None,
    emotional: bool = False,
) -> dict:
    path = Path(audio_path).expanduser()
    if not path.exists():
        raise ValueError(
            f"audio file not found: {path}. Pass a path readable by the MCP process "
            "on the machine that runs `voice-forge serve`."
        )
    if not path.is_file():
        raise ValueError(f"not a regular file: {path}. Pass the audio clip itself.")
    return client.clone_voice(
        str(path.resolve()),
        slug,
        name=name,
        language=language,
        transcript=transcript,
        emotional=emotional,
    )


def derive_voice(
    client: Any,
    slug: str,
    new_slug: str,
    name: str | None = None,
    pitch: float = -2.0,
    timbre: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    if timbre:
        # One purpose per derivation: a timbre source is not combined with a
        # semitone shift, so the pitch is not sent at all.
        return client.derive_voice(
            slug, new_slug, name=name, timbre=timbre, tags=tags
        )
    return client.derive_voice(
        slug, new_slug, name=name, pitch=pitch, tags=tags
    )


def get_previews(client: Any) -> list[dict]:
    return client.previews()


def engine_status(client: Any) -> dict:
    return client.engine_status()


def engine_action(client: Any, action: str) -> dict:
    if action not in ENGINE_ACTIONS:
        raise ValueError(
            f"unknown engine action {action!r}; expected one of {', '.join(ENGINE_ACTIONS)}"
        )
    return client.engine_action(action)


def queue_status(client: Any) -> dict:
    return client.queue_status()
