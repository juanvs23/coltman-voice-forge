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
from ....domain.errors import VoiceForgeError
from .context import UiContext, engine_prerequisites, queue_line
from .design import candidates_html, design_candidates, register_choice
from .engine import run_action
from .engine import status_report as engine_report
from .narrate import (
    EMPTY_ROW,
    MAX_LINES,
    VISIBLE_LINES,
    dialogue_from_rows,
    estimate_dialogue,
    estimate_script,
    render_dialogue,
    render_script,
    resolved_out,
)
from .preview import (
    EMOTION_AXES,
    EMOTION_PRESETS,
    axes_from,
    effective_axes,
    preview_once,
    slots_html,
)
from .styles import CONSOLE_CSS
from .voices import derive_voice, preview_ready, remove_voice, voices_table

DESIGN_TAB = """### Design

Describe the voice, generate candidates and audition them here. Registering
stores the chosen one exactly as `POST /api/voices/design` does; the neutral
rule is shown inline, with the word that triggered it."""

NARRATE_TAB = """### Narrate

Build a narration line by line, then render it to one mastered file. Each row
is a voice, its text, an emotion preset, a speed and the pause after it; a row
left blank is ignored. *Intensity* is global to the whole file.

Chapters and **acted** lines (`source:`) are only available in the raw YAML
editor under *Advanced* below. A line carries `text:` to be synthesised, or
`source: path/to/take.wav` to be acted: the recording is converted to the
line's `voice` and keeps its performance (`emotion`/`speed` are ignored on that
line). A relative `source:` resolves against the script's folder on disk, or
the server's working directory when the script arrives as text through the
API."""

NARRATE_YAML = """Chapters (`## chapter: name`) and acted lines (`source:`) live here,
because a form cannot express them. A blank or broken editor is one message,
never a traceback. Both render buttons use the same serial queue and the same
progress loop as the builder."""

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

UNPROBED_ENGINE = "engine · not probed · press **Refresh** for a live answer"

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
                # The cards are the screen; the two writes live one click away.
                with gr.Row():
                    with gr.Accordion("Derive a new voice", open=False):
                        derive_source = gr.Dropdown(slugs, label="Source voice", value=None)
                        derive_slug = gr.Textbox(label="New slug")
                        derive_name = gr.Textbox(label="New name (optional)")
                        derive_pitch = gr.Slider(
                            -6.0, 6.0, value=-2.0, step=0.5, label="Pitch (semitones)"
                        )
                        derive_timbre = gr.Dropdown(
                            slugs,
                            label="Timbre source (optional)",
                            value=None,
                            info="When set, the pitch slider is ignored.",
                        )
                        derive_button = gr.Button("Derive", variant="primary")
                    with gr.Accordion("Remove a voice", open=False):
                        remove_target = gr.Dropdown(slugs, label="Voice", value=None)
                        remove_button = gr.Button("Remove", variant="stop")

            with gr.Tab("Preview"):
                preview_voice = gr.Dropdown(slugs, label="Voice", value=None)
                preview_state = gr.Markdown(PREVIEW_IDLE)
                preview_text = gr.Textbox(
                    label="Text", lines=3, placeholder="La casa estaba vacía."
                )
                with gr.Row():
                    preview_emotion = gr.Dropdown(
                        list(EMOTION_PRESETS),
                        label="Emotion",
                        value="neutral",
                    )
                    preview_intensity = gr.Slider(
                        0.0, 1.0, value=0.6, step=0.05, label="Intensity"
                    )
                    preview_speed = gr.Slider(
                        0.5, 1.5, value=1.0, step=0.05, label="Speed"
                    )
                with gr.Accordion("Advanced: per-axis control", open=False):
                    gr.Markdown("Any axis above 0 overrides the preset.")
                    axis_sliders = []
                    with gr.Row():
                        for axis in EMOTION_AXES[:4]:
                            axis_sliders.append(_axis_slider(axis))
                    with gr.Row():
                        for axis in EMOTION_AXES[4:]:
                            axis_sliders.append(_axis_slider(axis))
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
                # Nothing to register before a take exists: the block appears
                # with the candidates instead of sitting there empty.
                with gr.Group(visible=False) as design_register_group:
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
                narrate_title = gr.Textbox(label="Title", value="narración")
                narrate_intensity = gr.Slider(
                    0.0, 1.0, value=0.6, step=0.05, label="Intensity (all lines)"
                )
                gr.Markdown("#### Output")
                with gr.Row():
                    narrate_out = gr.Textbox(
                        label="Output file", value="out/narrate.wav"
                    )
                    narrate_master = gr.Checkbox(label="Master LUFS", value=True)

                # Every row exists from the start; only the first three are
                # shown. Add/Remove toggle visibility and clear a hidden row,
                # so nothing is rebuilt and no stale text comes back.
                narrate_rows = []
                narrate_groups: list[gr.Group] = []
                for position in range(1, MAX_LINES + 1):
                    with gr.Group(visible=position <= VISIBLE_LINES) as row_group:
                        gr.Markdown(f"**Línea {position}**")
                        row_voice = gr.Dropdown(
                            slugs, label="Voice", value=None
                        )
                        row_text = gr.Textbox(
                            label="Text",
                            lines=2,
                            placeholder="La casa estaba vacía.",
                        )
                        with gr.Row():
                            row_emotion = gr.Dropdown(
                                list(EMOTION_PRESETS),
                                label="Emotion",
                                value="neutral",
                            )
                            row_speed = gr.Slider(
                                0.5, 1.5, value=1.0, step=0.05, label="Speed"
                            )
                            row_pause = gr.Number(
                                label="Pause after (ms)", value=350, precision=0
                            )
                    narrate_rows.append(
                        (row_voice, row_text, row_emotion, row_speed, row_pause)
                    )
                    narrate_groups.append(row_group)
                row_controls = [control for row in narrate_rows for control in row]
                narrate_line_count = gr.State(VISIBLE_LINES)
                with gr.Row():
                    narrate_add = gr.Button("Add line")
                    narrate_remove = gr.Button("Remove last line")
                with gr.Row():
                    narrate_build_validate = gr.Button("Validate + estimate")
                    narrate_build_render = gr.Button(
                        "Render lines", variant="primary"
                    )
                narrate_build_estimate = gr.Markdown("")
                narrate_message = gr.Markdown("")
                narrate_queue = gr.Markdown(queue_line(ctx.queue.snapshot()))
                narrate_audio = gr.Audio(type="filepath", label="Render")

                with gr.Accordion(
                    "Advanced: raw YAML (chapters, acted lines)", open=False
                ):
                    gr.Markdown(NARRATE_YAML)
                    narrate_script = gr.Code(
                        label="Script (YAML)",
                        language="yaml",
                        lines=14,
                        value=_default_script(),
                    )
                    narrate_validate = gr.Button("Validate YAML + estimate")
                    narrate_yaml_estimate = gr.Markdown("")
                    narrate_render = gr.Button("Render YAML", variant="primary")
            with gr.Tab("Engine"):
                gr.Markdown(ENGINE_TAB)
                engine_state = gr.Markdown(UNPROBED_ENGINE)
                engine_queue = gr.Markdown(queue_line(ctx.queue.snapshot()))
                with gr.Row():
                    engine_up = gr.Button("Up", variant="primary")
                    engine_warm = gr.Button("Warm")
                    engine_down = gr.Button("Down", variant="stop")
                    engine_refresh = gr.Button("Refresh")

        catalog_outputs = [
            header,
            voices_cards,
            voices_message,
            derive_source,
            derive_timbre,
            remove_target,
            preview_voice,
            *[row[0] for row in narrate_rows],
        ]
        voices_refresh.click(
            fn=lambda: _catalog_reply(
                ctx, voices_table(ctx), "Catalog refreshed.", MAX_LINES
            ),
            outputs=catalog_outputs,
        )
        derive_button.click(
            fn=_derive_call(ctx),
            inputs=[derive_source, derive_slug, derive_name, derive_pitch, derive_timbre],
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
                preview_emotion,
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
                design_register_group,
                design_register_message,
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

        narrate_build_validate.click(
            fn=_builder_estimate_call(),
            inputs=[narrate_title, narrate_intensity, *row_controls],
            outputs=narrate_build_estimate,
        )
        narrate_build_render.click(
            fn=_builder_render_call(ctx),
            inputs=[
                narrate_title,
                narrate_intensity,
                narrate_out,
                narrate_master,
                *row_controls,
            ],
            outputs=[narrate_message, narrate_queue, narrate_audio],
        )
        narrate_add.click(
            fn=_add_line,
            inputs=narrate_line_count,
            outputs=[narrate_line_count, *narrate_groups],
        )
        narrate_remove.click(
            fn=_remove_line,
            inputs=narrate_line_count,
            outputs=[narrate_line_count, *narrate_groups, *row_controls],
        )

        narrate_validate.click(
            fn=lambda script: estimate_script(script)[3],
            inputs=narrate_script,
            outputs=narrate_yaml_estimate,
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
    would require Node 24), ``analytics_enabled=False`` in ``Blocks`` keeps
    the console from phoning home, and ``footer_links=[]`` drops Gradio's own
    footer (API, "built with Gradio", settings, runs): the console documents
    itself, and the API docs are linked from the page instead.
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
        footer_links=[],
        # Gradio 6 dropped ``css`` from the Blocks constructor; the stylesheet
        # reaches the page through the mount. Without it every card class the
        # markup carries would render unstyled.
        css=CONSOLE_CSS,
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
    """The catalog in one line. Engine settings belong to the Engine tab."""
    voices = ctx.catalog.list()
    count = len(voices)
    plural = "voice" if count == 1 else "voices"
    parts = [f"**{count} {plural}**"]
    languages = sorted({voice.language for voice in voices})
    if languages:
        parts.append("languages: " + ", ".join(languages))

    lines = ["# voice-forge", "", " · ".join(parts)]
    missing = engine_prerequisites(ctx)
    if missing:
        # A static fact, true from build time: the engine could not start. The
        # live engine state belongs to the Engine tab, which can actually be
        # refreshed; a "not probed" line painted once would keep saying it
        # after the operator probed it.
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


def _catalog_reply(
    ctx: UiContext, cards: str, message: str, extra_dropdowns: int = 0
):
    """Header, cards, message and every voice dropdown, from the live catalog.

    ``extra_dropdowns`` covers the builder's rows: they list the catalog too,
    so a voice registered elsewhere must appear there without a page reload.
    """
    return (
        _header(ctx),
        cards,
        message,
        *[_dropdown_update(ctx) for _ in range(4 + extra_dropdowns)],
    )


def _derive_call(ctx: UiContext):
    def run(slug, new_slug, name, pitch, timbre):
        cards, message = derive_voice(ctx, slug, new_slug, name, pitch, timbre)
        return _catalog_reply(ctx, cards, message, MAX_LINES)

    return run


def _remove_call(ctx: UiContext):
    def run(slug):
        cards, message = remove_voice(ctx, slug)
        return _catalog_reply(ctx, cards, message, MAX_LINES)

    return run


def _register_call(ctx: UiContext):
    def run(state, pick, slug, name, tags, emotional):
        message, cards = register_choice(ctx, state, pick, slug, name, tags, emotional)
        return _catalog_reply(ctx, cards, message, MAX_LINES)

    return run


def _preview_call(ctx: UiContext):
    """Bind the context, then unpack the preset and the eight sliders.

    The inputs are ``slug, text, preset`` followed by the eight ``EMOTION_AXES``
    sliders in order, then intensity, speed and hint. ``effective_axes``
    decides which emotion the take gets: *any* slider above 0 means the
    operator used *Advanced* and those axes win; with every slider at 0 the
    preset alone decides, and `neutral` means no axes at all.
    """
    count = len(EMOTION_AXES)

    def run(slug, text, preset, *values):
        axes = effective_axes(preset, axes_from(values[:count]))
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


def _builder_estimate_call():
    """Estimate the dialogue the builder's rows describe, without a model."""

    def run(title, intensity, *values):
        try:
            dialogue = dialogue_from_rows(_row_values(values), title, intensity)
        except VoiceForgeError as exc:
            return f"**Script rejected** — {exc}"
        return estimate_dialogue(dialogue)[3]

    return run


def _builder_render_call(ctx: UiContext):
    """Build the dialogue from the rows, then stream the shared render loop."""

    def run(title, intensity, out_path, master, *values):
        try:
            dialogue = dialogue_from_rows(_row_values(values), title, intensity)
        except VoiceForgeError as exc:
            yield (
                f"**Script rejected** — {exc}",
                queue_line(ctx.queue.snapshot()),
                None,
            )
            return
        target = resolved_out(ctx, out_path)
        for message, queue in render_dialogue(ctx, dialogue, out_path, master):
            audio = str(target) if target.is_file() else None
            yield message, queue, audio

    return run


def _row_values(values: tuple[object, ...]) -> list[tuple[object, ...]]:
    """Five controls per row, in the order the builder wired them."""
    return [
        tuple(values[index * 5 : index * 5 + 5]) for index in range(MAX_LINES)
    ]


def _add_line(count) -> tuple[object, ...]:
    """Reveal the next hidden row; with every row shown, keep all of them."""
    shown = min(MAX_LINES, int(count or 0) + 1)
    return (shown, *[gr.update(visible=index < shown) for index in range(MAX_LINES)])


def _remove_line(count) -> tuple[object, ...]:
    """Hide the last shown row and clear it, so re-adding starts empty."""
    current = int(count or 0)
    hidden = current - 1
    shown = max(0, hidden)
    clears: list[object] = []
    for index in range(MAX_LINES):
        if index == hidden and current > 0:
            clears.extend(gr.update(value=value) for value in EMPTY_ROW)
        else:
            clears.extend(gr.update() for _ in EMPTY_ROW)
    return (
        shown,
        *[gr.update(visible=index < shown) for index in range(MAX_LINES)],
        *clears,
    )


def _narrate_call(ctx: UiContext):
    """Stream the render: message, queue line and the file once it exists."""

    def run(script, out_path, master):
        target = resolved_out(ctx, out_path)
        for message, queue in render_script(ctx, script, out_path, master):
            audio = str(target) if target.is_file() else None
            yield message, queue, audio

    return run


def _design_call(ctx: UiContext):
    """Bind the context and reveal the register block once a take exists."""

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
            gr.update(visible=bool(choices)),
            "",
        )

    return run
