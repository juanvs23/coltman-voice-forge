"""Operator console, mounted at ``/ui``.

Every button calls a pure function from ``voices.py``/``preview.py``/
``design.py``/``engine.py``; this module only wires inputs to outputs.
Gradio's own queue is never used: ``SerialQueue`` is the only planner and the
UI just displays its state.
"""

from __future__ import annotations

import gradio as gr
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from gradio import mount_gradio_app

from ....config import PROJECT_ROOT
from ....container import Container
from .context import UiContext, engine_prerequisites, queue_line, status_report
from .design import candidates_html, design_candidates, register_choice
from .engine import run_action
from .engine import status_report as engine_report
from .narrate import estimate_script, render_script, resolved_out
from .preview import EMOTION_AXES, axes_from, preview_once, slots_html
from .voices import derive_voice, preview_ready, remove_voice, voices_table

DESIGN_TAB = """### Design

Describe the voice, generate candidates and audition them here. Registering
stores the chosen one exactly as `POST /api/voices/design` does; the neutral
rule is shown inline, with the word that triggered it."""

NARRATE_TAB = """### Narrate

`POST /api/dialogues/render` turns a YAML script into one mastered file. The
editor below validates and estimates the same script the API parses; a render
goes through the serial queue and the page reports `busy`/`pending` while it
runs."""

FALLBACK_SCRIPT = """title: demo
lines:
  - voice: narrador
    text: "La casa llevaba veinte años vacía."
    emotion: { melancholic: 0.45, calm: 0.60 }
    pause_after_ms: 600
"""

ENGINE_TAB = """### Engine

`up` / `warm` / `down` through the same controls the CLI uses, plus the real
status and the queue depth. Nothing is probed until you click."""

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
        header = gr.Markdown(_header(ctx))

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
                design_description = gr.Textbox(
                    label="Voice description",
                    lines=2,
                    placeholder="A warm, low-pitched narrator with a calm pace",
                )
                with gr.Row():
                    design_language = gr.Textbox(label="Language", value="Spanish")
                    design_count = gr.Slider(
                        2, 6, value=4, step=1, label="Candidates"
                    )
                    design_seed = gr.Number(
                        label="Seed (optional)", value=None, precision=0
                    )
                design_preview_text = gr.Textbox(
                    label="Preview text (optional)",
                    placeholder="La casa estaba vacía.",
                )
                design_emotional = gr.Checkbox(
                    label="Accept a non-neutral reference", value=False
                )
                design_generate = gr.Button("Generate candidates", variant="primary")
                design_message = gr.Markdown("")
                design_players = gr.HTML(candidates_html([]))
                design_state = gr.State({})
                gr.Markdown("#### Register the chosen candidate")
                with gr.Row():
                    design_pick = gr.Dropdown([], label="Candidate to register")
                    design_slug = gr.Textbox(label="Slug")
                    design_name = gr.Textbox(label="Name (optional)")
                    design_tags = gr.Textbox(label="Tags (comma separated)", value="")
                design_register = gr.Button("Register", variant="primary")
                design_register_message = gr.Markdown("")

            with gr.Tab("Narrate"):
                gr.Markdown(NARRATE_TAB)
                narrate_script = gr.Code(
                    label="Script (YAML)",
                    language="yaml",
                    lines=14,
                    value=_default_script(),
                )
                with gr.Row():
                    narrate_validate = gr.Button("Validate + estimate")
                    narrate_render = gr.Button("Render", variant="primary")
                narrate_estimate = gr.Markdown("")
                with gr.Row():
                    narrate_out = gr.Textbox(
                        label="Output file", value="out/narrate.wav"
                    )
                    narrate_master = gr.Checkbox(label="Master LUFS", value=True)
                narrate_message = gr.Markdown("")
                narrate_queue = gr.Markdown(queue_line(ctx.queue.snapshot()))
                narrate_audio = gr.Audio(type="filepath", label="Render")
            with gr.Tab("Engine"):
                gr.Markdown(ENGINE_TAB)
                engine_state = gr.Markdown(UNPROBED_ENGINE)
                engine_queue = gr.Markdown(queue_line(ctx.queue.snapshot()))
                with gr.Row():
                    engine_up = gr.Button("Up", variant="primary")
                    engine_warm = gr.Button("Warm")
                    engine_down = gr.Button("Down", variant="stop")
                    engine_refresh = gr.Button("Refresh")

        refresh = gr.Button("Refresh status")
        status = gr.Markdown(f"{UNPROBED_ENGINE}\n\n{queue_line(ctx.queue.snapshot())}")
        refresh.click(fn=lambda: status_report(ctx), outputs=status)

        catalog_outputs = [
            header,
            voices_cards,
            voices_message,
            derive_source,
            remove_target,
            preview_voice,
        ]
        voices_refresh.click(
            fn=lambda: _catalog_reply(ctx, voices_table(ctx), "Catalog refreshed."),
            outputs=catalog_outputs,
        )
        derive_button.click(
            fn=_derive_call(ctx),
            inputs=[derive_source, derive_slug, derive_name, derive_pitch],
            outputs=catalog_outputs,
        )
        remove_button.click(
            fn=_remove_call(ctx),
            inputs=remove_target,
            outputs=catalog_outputs,
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

        design_generate.click(
            fn=_design_call(ctx),
            inputs=[
                design_description,
                design_language,
                design_count,
                design_seed,
                design_preview_text,
                design_emotional,
            ],
            outputs=[
                design_message,
                design_state,
                design_players,
                design_pick,
            ],
        )
        design_register.click(
            fn=_register_call(ctx),
            inputs=[
                design_state,
                design_pick,
                design_slug,
                design_name,
                design_tags,
                design_emotional,
            ],
            outputs=[design_register_message, *catalog_outputs],
        )

        narrate_validate.click(
            fn=lambda script: estimate_script(script)[3],
            inputs=narrate_script,
            outputs=narrate_estimate,
        )
        narrate_render.click(
            fn=_narrate_call(ctx),
            inputs=[narrate_script, narrate_out, narrate_master],
            outputs=[narrate_message, narrate_queue, narrate_audio],
        )

        engine_refresh.click(
            fn=lambda: engine_report(ctx),
            outputs=[engine_state, engine_queue],
        )
        for button, action in (
            (engine_up, "up"),
            (engine_warm, "warm"),
            (engine_down, "down"),
        ):
            button.click(
                fn=lambda chosen=action: run_action(ctx, chosen),
                outputs=[engine_state, engine_queue],
            )

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
        # A static fact, true from build time: the engine could not start. The
        # live engine state belongs to the Engine tab and the status button,
        # which can actually be refreshed; a "not probed" line painted once
        # would keep saying it after the operator probed it.
        lines += ["", "> **Engine cannot start yet** — " + "; ".join(missing)]
    return "\n".join(lines)


def _slugs(ctx: UiContext) -> list[str]:
    return [voice.slug for voice in ctx.catalog.list()]


def _axis_slider(axis) -> gr.Slider:
    return gr.Slider(0.0, 1.0, value=0.0, step=0.05, label=axis.value)


def _dropdown_update(ctx: UiContext):
    """A fresh voice list for every dropdown that lists the catalog.

    The console is long-lived; a voice registered in Design must be selectable
    in Preview without reloading the page.
    """
    return gr.update(choices=_slugs(ctx), value=None)


def _catalog_reply(ctx: UiContext, cards: str, message: str):
    """Header, cards, message and all three dropdowns, from the live catalog."""
    return (
        _header(ctx),
        cards,
        message,
        _dropdown_update(ctx),
        _dropdown_update(ctx),
        _dropdown_update(ctx),
    )


def _derive_call(ctx: UiContext):
    def run(slug, new_slug, name, pitch):
        cards, message = derive_voice(ctx, slug, new_slug, name, pitch)
        return _catalog_reply(ctx, cards, message)

    return run


def _remove_call(ctx: UiContext):
    def run(slug):
        cards, message = remove_voice(ctx, slug)
        return _catalog_reply(ctx, cards, message)

    return run


def _register_call(ctx: UiContext):
    def run(state, pick, slug, name, tags, emotional):
        message, cards = register_choice(ctx, state, pick, slug, name, tags, emotional)
        return _catalog_reply(ctx, cards, message)

    return run


def _preview_call(ctx: UiContext):
    """Bind the context, then unpack the eight sliders in ``EMOTION_AXES`` order."""
    count = len(EMOTION_AXES)

    def run(slug, text, *values):
        axes = axes_from(values[:count])
        intensity, speed, hint = values[count : count + 3]
        return preview_once(ctx, slug, text, axes, intensity, speed, hint)

    return run


def _default_script() -> str:
    """Seed the editor with the example script; a minimal template without it."""
    path = PROJECT_ROOT / "examples" / "dialogo.yaml"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return FALLBACK_SCRIPT


def _narrate_call(ctx: UiContext):
    """Stream the render: message, queue line and the file once it exists."""

    def run(script, out_path, master):
        target = resolved_out(ctx, out_path)
        for message, queue in render_script(ctx, script, out_path, master):
            audio = str(target) if target.is_file() else None
            yield message, queue, audio

    return run


def _design_call(ctx: UiContext):
    """Bind the context and keep the candidate selector in step with the take."""

    def run(description, language, count, seed, preview_text, emotional):
        message, state, markup = design_candidates(
            ctx, description, language, count, seed, preview_text, emotional
        )
        choices = [entry["index"] for entry in state.get("candidates", [])]
        return (
            message,
            state,
            markup,
            gr.update(choices=choices, value=choices[0] if choices else None),
        )

    return run
