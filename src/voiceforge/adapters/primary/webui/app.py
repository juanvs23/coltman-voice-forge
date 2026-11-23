"""Operator console, mounted at ``/ui``.

This slice mounts Gradio and states honestly what exists. Every tab points at
the API call that already works, so a missing screen never reads as a missing
capability. Screens arrive in the next slices; no handler is invented here.
"""

from __future__ import annotations

import gradio as gr
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from gradio import mount_gradio_app

from ....container import Container
from .context import UiContext, engine_prerequisites, queue_line, status_report

VOICES_TAB = """### Voices

`GET /api/voices` already lists every voice with its origin, language and
recipe; `GET /api/voices/{slug}` shows one. The table, the register form and
the derive flow arrive in the next slice."""

PREVIEW_TAB = """### Preview

`POST /api/voices/{slug}/preview` renders a take into the three fixed preview
slots and `GET /api/previews` lists them. The player and the emotion controls
arrive in the next slice — meanwhile use the API or `voice-forge preview`."""

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


def build_console(container: Container) -> gr.Blocks:
    """Build the console for one container. No network, no model call."""
    ctx = UiContext.from_container(container)
    with gr.Blocks(title="voice-forge", analytics_enabled=False) as blocks:
        gr.Markdown(_header(ctx))

        with gr.Tabs():
            with gr.Tab("Voices"):
                gr.Markdown(VOICES_TAB)
            with gr.Tab("Preview"):
                gr.Markdown(PREVIEW_TAB)
            with gr.Tab("Design"):
                gr.Markdown(DESIGN_TAB)
            with gr.Tab("Narrate"):
                gr.Markdown(NARRATE_TAB)
            with gr.Tab("Engine"):
                gr.Markdown(ENGINE_TAB)

        refresh = gr.Button("Refresh status")
        status = gr.Markdown(f"{UNPROBED_ENGINE}\n\n{queue_line(ctx.queue.snapshot())}")
        refresh.click(fn=lambda: status_report(ctx), outputs=status)

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
