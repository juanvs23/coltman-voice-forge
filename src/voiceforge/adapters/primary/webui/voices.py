"""Voices screen: catalog cards and the catalog actions.

Every function is pure — ``ctx`` plus primitives in, strings and tuples out —
so ``app.py`` only wires clicks and the behaviour stays testable without a
browser. No handler here raises: the console reports, it never prints a
traceback at the operator.
"""

from __future__ import annotations

import html
from typing import Iterable

from ....domain.errors import VoiceForgeError
from ....domain.models import Voice
from .context import UiContext, engine_line, recipe_summary

ORIGINS = ("designed", "imported", "derived")


# ── cards ───────────────────────────────────────────────────────────────
def cards_html(voices: Iterable[Voice]) -> str:
    """One card per voice; the empty catalog is said, not left blank."""
    cards = [_card(voice) for voice in voices]
    if not cards:
        return (
            '<p class="vf-empty">The catalog is empty. Design a voice from a '
            "description or add a reference clip first.</p>"
        )
    return '<div class="vf-cards">' + "".join(cards) + "</div>"


def _card(voice: Voice) -> str:
    origin = voice.origin if voice.origin in ORIGINS else "imported"
    rows = [
        ("language", html.escape(voice.language)),
        ("sample rate", f"{voice.sample_rate:,} Hz"),
        ("recipe", html.escape(recipe_summary(voice))),
    ]
    if voice.ref_transcript:
        rows.append(("transcript", html.escape(voice.ref_transcript)))

    derived = voice.recipe.get("derived_from")
    derived_html = (
        f'\n    <p class="vf-derived">derived from '
        f"<code>{html.escape(str(derived))}</code></p>"
        if derived
        else ""
    )
    definition = "".join(
        f"\n      <dt>{label}</dt><dd>{value}</dd>" for label, value in rows
    )
    return (
        f'<article class="vf-card vf-origin-{origin}" data-slug="{html.escape(voice.slug)}">'
        f'\n  <header class="vf-card-head">'
        f'\n    <h3 class="vf-name">{html.escape(voice.name)}</h3>'
        f'\n    <span class="vf-badge vf-badge-{origin}">{origin}</span>'
        f"\n  </header>"
        f'\n  <p class="vf-slug"><code>{html.escape(voice.slug)}</code></p>'
        f'\n  <dl class="vf-meta">{definition}\n  </dl>{derived_html}'
        f"\n</article>"
    )


def voices_table(ctx: UiContext) -> str:
    """The refreshed cards; what the Refresh button prints."""
    return cards_html(ctx.catalog.list())


# ── readiness ───────────────────────────────────────────────────────────
def preview_ready(ctx: UiContext, slug: str | None) -> str:
    """Whether a take can run right now, and why not when it cannot."""
    target = (slug or "").strip()
    if not target:
        return "Pick a voice to audition."
    try:
        voice = ctx.catalog.get(target)
    except VoiceForgeError as exc:
        return f"No voice `{target}` in the catalog — {exc}"
    try:
        status = dict(ctx.engine.status())
    except Exception as exc:  # noqa: BLE001 - a dead host must not break the page
        return f"engine · unreachable · {exc} — run `voice-forge up` before auditioning."
    line = engine_line(status)
    if str(status.get("status")) == "down":
        return (
            f"{line} — a take of `{voice.slug}` needs the model host, "
            "so preview stays disabled until then."
        )
    return f"{line} — ready to audition `{voice.slug}`."


# ── actions ─────────────────────────────────────────────────────────────
def derive_voice(
    ctx: UiContext,
    slug: str | None,
    new_slug: str | None,
    name: str | None,
    pitch: float | None,
) -> tuple[str, str]:
    """Derive a new voice from ``slug``. Returns (refreshed cards, message)."""
    source = (slug or "").strip()
    target = (new_slug or "").strip()
    if not source or not target:
        return cards_html(ctx.catalog.list()), "Pick a source voice and type a new slug."
    try:
        semitones = float(pitch) if pitch is not None else 0.0
    except (TypeError, ValueError):
        return (
            cards_html(ctx.catalog.list()),
            f"Pitch must be a number within -6..6 semitones, got {pitch!r}.",
        )
    try:
        voice = ctx.derive.derive(
            source,
            slug=target,
            name=(name or "").strip() or None,
            pitch_semitones=semitones,
        )
    except (VoiceForgeError, OSError) as exc:
        return cards_html(ctx.catalog.list()), f"Could not derive `{target}`: {exc}"
    return cards_html(ctx.catalog.list()), (
        f"Derived `{voice.slug}` from `{source}` at {semitones:+g} semitones. "
        "The source clip was not touched."
    )


def remove_voice(ctx: UiContext, slug: str | None) -> tuple[str, str]:
    """Remove one voice. Returns (refreshed cards, message)."""
    target = (slug or "").strip()
    if not target:
        return cards_html(ctx.catalog.list()), "Pick a voice to remove."
    try:
        ctx.catalog.remove(target)
    except (VoiceForgeError, OSError) as exc:
        return cards_html(ctx.catalog.list()), f"Could not remove `{target}`: {exc}"
    return cards_html(ctx.catalog.list()), (
        f"Removed `{target}`. Its reference clip is gone; a new slug would need a new clip."
    )
