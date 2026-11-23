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
    """One card per voice, ordered by name; an empty catalog says so."""
    ordered = sorted(voices, key=lambda voice: voice.name.casefold())
    cards = [_card(voice) for voice in ordered]
    if not cards:
        return (
            '<p class="vf-empty">The catalog is empty. Design a voice from a '
            "description or add a reference clip first.</p>"
        )
    count = len(cards)
    label = "voice" if count == 1 else "voices"
    return (
        f'<p class="vf-count">{count} {label}</p>'
        '<div class="vf-cards">' + "".join(cards) + "</div>"
    )


def _card(voice: Voice) -> str:
    origin = voice.origin if voice.origin in ORIGINS else "imported"
    chips = [
        f'<span class="vf-chip">{html.escape(voice.language)}</span>',
        f'<span class="vf-chip">{voice.sample_rate:,} Hz</span>',
    ]
    if voice.reference_neutral is False:
        chips.append(
            '<span class="vf-chip vf-chip-warn">non-neutral reference</span>'
        )
    chips.extend(
        f'<span class="vf-chip vf-tag">{html.escape(tag)}</span>'
        for tag in voice.tags
    )

    lineage = _lineage(voice)
    transcript = (
        f'\n  <p class="vf-transcript">{html.escape(voice.ref_transcript)}</p>'
        if voice.ref_transcript
        else ""
    )
    return (
        f'<article class="vf-card vf-origin-{origin}" data-slug="{html.escape(voice.slug)}">'
        f'\n  <header class="vf-card-head">'
        f'\n    <h3 class="vf-name">{html.escape(voice.name)}</h3>'
        f'\n    <span class="vf-badge vf-badge-{origin}">{origin}</span>'
        f"\n  </header>"
        f'\n  <code class="vf-slug">{html.escape(voice.slug)}</code>'
        f'\n  <div class="vf-chips">{"".join(chips)}</div>'
        f'\n  <p class="vf-recipe">{html.escape(recipe_summary(voice))}</p>'
        f"{transcript}{lineage}"
        f"\n</article>"
    )


def _lineage(voice: Voice) -> str:
    """Where a derived voice came from; nothing for the other origins."""
    derived = voice.recipe.get("derived_from")
    timbre = voice.recipe.get("timbre_from")
    parts = []
    if derived:
        parts.append(f"derived from <code>{html.escape(str(derived))}</code>")
    if timbre:
        parts.append(f"timbre <code>{html.escape(str(timbre))}</code>")
    if not parts:
        return ""
    return f'\n  <p class="vf-lineage">{" · ".join(parts)}</p>'


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
    timbre: str | None = None,
) -> tuple[str, str]:
    """Derive a new voice from ``slug``. Returns (refreshed cards, message).

    ``timbre`` wins over ``pitch`` when both arrive: the dropdown is explicit,
    and a timbre conversion has no use for a semitone value. The conversion is
    model work, so it enters the serial queue like every other take.
    """
    source = (slug or "").strip()
    target = (new_slug or "").strip()
    if not source or not target:
        return cards_html(ctx.catalog.list()), "Pick a source voice and type a new slug."
    timbre_from = (timbre or "").strip() or None
    semitones: float | None = None
    if timbre_from is None:
        try:
            semitones = float(pitch) if pitch is not None else 0.0
        except (TypeError, ValueError):
            return (
                cards_html(ctx.catalog.list()),
                f"Pitch must be a number within -6..6 semitones, got {pitch!r}.",
            )
    try:
        job = ctx.queue.submit(
            "derive",
            lambda: ctx.derive.derive(
                source,
                slug=target,
                name=(name or "").strip() or None,
                pitch_semitones=semitones,
                timbre_from=timbre_from,
            ),
        )
        finished = ctx.queue.wait(job.id, timeout=300)
        if finished.state != "done":
            raise VoiceForgeError(finished.error or "the derive job did not finish")
        voice = finished.result
    except (VoiceForgeError, OSError, RuntimeError) as exc:
        return cards_html(ctx.catalog.list()), f"Could not derive `{target}`: {exc}"
    if timbre_from:
        return cards_html(ctx.catalog.list()), (
            f"Derived `{voice.slug}` from `{source}` with the timbre of "
            f"`{timbre_from}`. The source clip was not touched."
        )
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
