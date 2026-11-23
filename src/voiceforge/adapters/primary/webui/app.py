"""Operator console, mounted at ``/ui``.

This slice fills the Voices and Preview screens. Every button calls a pure
function from ``voices.py``/``preview.py``; this module only wires inputs to
outputs. Gradio's own queue is never used: ``SerialQueue`` is the only planner
and the UI just displays its state.
"""

from __future__ import annotations

import gradio as gr
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from gradio import mount_gradio_app

from ....container import Container
from .context import UiContext, engine_prerequisites, queue_line, status_report
from .preview import EMOTION_AXES, axes_from, preview_once, slots_html
from .voices import derive_voice, preview_ready, remove_voice, voices_table

DESIGN_TAB = """### Design

`POST /api/voices/design` creates a voice from a text description and returns
the picked candidate. Candidate audition and the neutral-reference warning
arrive in the next slice."""

NARRATE_TAB = """### Narrate

`POST /api/dialogues/render` turns a YAML script into one mastered file. The
script editor, per-line emotion and render history arrive in the next slice."""

ENGINE_TAB = """### Engine

`GET /api/engine` reads the host health; `POST /api/engine/{up,warm,down}`
drives it. This tab will own those buttons. Until then, **Refresh status**
below reports the live state and the queue depth."""

FOOTER = """---
This console is a client of the same API the CLI uses, not a second backend.
Interactive docs: [`/docs`](/docs) · JSON: `/api/voices`, `/api/previews`,
`/api/engine`, `/api/queue`."""

UNPROBED_ENGINE = "engine · not probed · press **Refresh status** for a live answer"

PREVIEW_IDLE = "Pick a voice to audition."


def build_console(container: Container) -> gr.Blocks:
    """Build the console for one container. No network, no model call."""
    ctx = UiContext.from_container(container)
    slugs = _slugs(ctx)
    with gr.Blocks(title="voice-forge", analytics_enabled=False) as blocks:
        gr.Markdown(_header(ctx))

        with gr.Tabs():
            with gr.Tab("Voices"):
                voices_cards = gr.HTML(voices_table(ctx))
                with gr.Row():
                    voices_refresh = gr.Button("Refresh")
                voices_message = gr.Markdown("")
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### Derive a new voice")
                        derive_source = gr.Dropdown(slugs, label="Source voice", value=None)
                        derive_slug = gr.Textbox(label="New slug")
                        derive_name = gr.Textbox(label="New name (optional)")
                        derive_pitch = gr.Slider(
                            -6.0, 6.0, value=-2.0, step=0.5, label="Pitch (semitones)"
                        )
                        derive_button = gr.Button("Derive", variant="primary")
                    with gr.Column():
                        gr.Markdown("#### Remove a voice")
                        remove_target = gr.Dropdown(slugs, label="Voice", value=None)
                        remove_button = gr.Button("Remove", variant="stop")

            with gr.Tab("Preview"):
                preview_voice = gr.Dropdown(slugs, label="Voice", value=None)
                preview_state = gr.Markdown(PREVIEW_IDLE)
                preview_text = gr.Textbox(
                    label="Text", lines=3, placeholder="La casa estaba vacía."
                )
                gr.Markdown("#### Emotion axes · 0 is neutral")
                axis_sliders = []
                with gr.Row():
                    for axis in EMOTION_AXES[:4]:
                        axis_sliders.append(_axis_slider(axis))
                with gr.Row():
                    for axis in EMOTION_AXES[4:]:
                        axis_sliders.append(_axis_slider(axis))
                with gr.Row():
                    preview_intensity = gr.Slider(
                        0.0, 1.0, value=0.6, step=0.05, label="Intensity"
                    )
                    preview_speed = gr.Slider(
                        0.5, 1.5, value=1.0, step=0.05, label="Speed"
                    )
                preview_hint = gr.Textbox(
                    label="Hint (optional)", placeholder="whispered, slow, close to the mic"
                )
                preview_button = gr.Button("Render take", variant="primary")
                preview_audio = gr.Audio(type="filepath", label="Take")
                preview_message = gr.Markdown("")
                slots_view = gr.HTML(slots_html(ctx))
                slots_refresh = gr.Button("Refresh slots")

            with gr.Tab("Design"):
                gr.Markdown(DESIGN_TAB)
            with gr.Tab("Narrate"):
                gr.Markdown(NARRATE_TAB)
            with gr.Tab("Engine"):
                gr.Markdown(ENGINE_TAB)

        refresh = gr.Button("Refresh status")
        status = gr.Markdown(f"{UNPROBED_ENGINE}\n\n{queue_line(ctx.queue.snapshot())}")
        refresh.click(fn=lambda: status_report(ctx), outputs=status)

        voices_refresh.click(
            fn=lambda: (voices_table(ctx), "Catalog refreshed."),
            outputs=[voices_cards, voices_message],
        )
        derive_button.click(
            fn=lambda slug, new_slug, name, pitch: derive_voice(
                ctx, slug, new_slug, name, pitch
            ),
            inputs=[derive_source, derive_slug, derive_name, derive_pitch],
            outputs=[voices_cards, voices_message],
        )
        remove_button.click(
            fn=lambda slug: remove_voice(ctx, slug),
            inputs=remove_target,
            outputs=[voices_cards, voices_message],
        )
        preview_voice.change(
            fn=lambda slug: preview_ready(ctx, slug),
            inputs=preview_voice,
            outputs=preview_state,
        )
        preview_button.click(
            fn=_preview_call(ctx),
            inputs=[
                preview_voice,
                preview_text,
                *axis_sliders,
                preview_intensity,
                preview_speed,
                preview_hint,
            ],
            outputs=[preview_audio, preview_message, slots_view],
        )
        slots_refresh.click(fn=lambda: slots_html(ctx), outputs=slots_view)

        gr.Markdown(FOOTER)
    return blocks


def mount_console(app: FastAPI, container: Container, *, path: str = "/ui") -> FastAPI:
    """Attach the console to the API app.

    Gradio is imported only inside this package; the rest of the system must
    not depend on it. ``ssr_mode=False`` keeps the page client-rendered (SSR
    would require Node 24), and ``analytics_enabled=False`` in ``Blocks``
    keeps the console from phoning home.
    """
    path = "/" + path.strip("/")
    if path != "/":
        # Starlette mounts only match ``path/``, so ``GET /ui`` alone is a 307.
        # Answering 200 with Gradio's own page would break it: its ``base
        # href="./"`` would resolve against ``/`` instead of ``/ui/``. A tiny
        # entry page keeps the documented URL honest and the assets correct.
        @app.get(path, response_class=HTMLResponse, include_in_schema=False)
        async def _console_entry() -> str:
            return _entry_html(path + "/")
    return mount_gradio_app(
        app,
        build_console(container),
        path=path,
        ssr_mode=False,
    )


def _entry_html(target: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f'<meta http-equiv="refresh" content="0; url={target}">\n'
        "<title>voice-forge</title>\n"
        "</head>\n"
        "<body>\n"
        f'<p>Opening the voice-forge console at <a href="{target}">{target}</a>.</p>\n'
        "</body>\n"
        "</html>\n"
    )


def _header(ctx: UiContext) -> str:
    voices = ctx.catalog.list()
    count = len(voices)
    plural = "voice" if count == 1 else "voices"
    parts = [f"**{count} {plural}**"]
    languages = sorted({voice.language for voice in voices})
    if languages:
        parts.append("languages: " + ", ".join(languages))
    settings = ctx.settings
    parts.append(f"adapter `{settings.adapter}` · device `{settings.device}`")

    lines = ["# voice-forge", "", " · ".join(parts)]
    missing = engine_prerequisites(ctx)
    if missing:
        lines += ["", "> **Engine cannot start yet** — " + "; ".join(missing)]
    else:
        lines += ["", UNPROBED_ENGINE + "."]
    return "\n".join(lines)


def _slugs(ctx: UiContext) -> list[str]:
    return [voice.slug for voice in ctx.catalog.list()]


def _axis_slider(axis) -> gr.Slider:
    return gr.Slider(0.0, 1.0, value=0.0, step=0.05, label=axis.value)


def _preview_call(ctx: UiContext):
    """Bind the context, then unpack the eight sliders in ``EMOTION_AXES`` order."""
    count = len(EMOTION_AXES)

    def run(slug, text, *values):
        axes = axes_from(values[:count])
        intensity, speed, hint = values[count : count + 3]
        return preview_once(ctx, slug, text, axes, intensity, speed, hint)

    return run
