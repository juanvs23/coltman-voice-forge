"""HTTP adapter: REST API + a small practical UI.

Swagger at /docs comes free; the UI at / is for daily use.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from ...container import Container
from ...domain.errors import (
    EngineAlreadyRunning,
    EngineBusy,
    EngineUnavailable,
    VoiceForgeError,
    VoiceNotFound,
)
from ...domain.models import VoiceBrief
from ...domain.script import parse_dialogue
from .ui import INDEX_HTML


class DesignRequest(BaseModel):
    description: str
    slug: str
    name: str | None = None
    language: str = "Spanish"
    candidates: int = 4
    pick: int = 0
    seed: int | None = None
    preview_text: str | None = None
    tags: list[str] = []


class RenderRequest(BaseModel):
    script: str
    out: str | None = None
    lufs: float = -14.0
    master: bool = True


def create_app(container: Container) -> FastAPI:
    app = FastAPI(title="voice-forge", version="0.1.0")

    # ── errors ──────────────────────────────────────────────────────────
    @app.exception_handler(VoiceNotFound)
    async def _not_found(_request, exc: VoiceNotFound):
        return JSONResponse({"error": str(exc)}, status_code=404)

    @app.exception_handler(EngineUnavailable)
    async def _engine_down(_request, exc: EngineUnavailable):
        return JSONResponse({"error": str(exc), "hint": "run `voice-forge up`"}, status_code=503)

    @app.exception_handler(EngineAlreadyRunning)
    async def _already_running(_request, exc: EngineAlreadyRunning):
        return JSONResponse(
            {"error": str(exc), "hint": "one instance only; stop it with `voice-forge down`"},
            status_code=409,
        )

    @app.exception_handler(EngineBusy)
    async def _busy(_request, exc: EngineBusy):
        return JSONResponse({"error": str(exc), "hint": "wait, or force with --force"}, status_code=409)

    @app.exception_handler(VoiceForgeError)
    async def _domain_error(_request, exc: VoiceForgeError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    # ── ui ──────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return INDEX_HTML

    # ── voices ──────────────────────────────────────────────────────────
    @app.get("/api/voices")
    async def list_voices():
        return [
            {
                "slug": voice.slug,
                "name": voice.name,
                "origin": voice.origin,
                "language": voice.language,
                "sample_rate": voice.sample_rate,
                "tags": list(voice.tags),
                "recipe": dict(voice.recipe),
            }
            for voice in container.catalog.list()
        ]

    @app.get("/api/queue")
    async def queue_state():
        return container.queue.snapshot()

    @app.get("/api/runtime")
    async def runtime_status():
        return container.runtime.status()

    @app.get("/api/runtime/plan")
    async def runtime_plan(backend: str = "auto"):
        return container.runtime.plan(backend).as_dict()

    @app.post("/api/voices/design", status_code=201)
    async def design_voice(request: DesignRequest):
        brief = VoiceBrief(
            description=request.description,
            language=request.language,
            candidates=request.candidates,
            seed=request.seed,
            preview_text=request.preview_text,
        )
        job = container.queue.submit(
            "design",
            lambda: container.catalog.design(
                brief,
                slug=request.slug,
                name=request.name,
                pick=request.pick,
                tags=request.tags,
            ),
        )
        finished = container.queue.wait(job.id, timeout=1800)
        if finished.state != "done":
            raise VoiceForgeError(finished.error or "the design job did not finish")
        voice, candidates = finished.result
        return {
            "job": job.id,
            "voice": {"slug": voice.slug, "name": voice.name, "origin": voice.origin},
            "candidates": len(candidates),
            "picked": request.pick,
        }

    @app.post("/api/voices", status_code=201)
    async def register_voice(
        file: UploadFile = File(...),
        slug: str = Form(...),
        name: str | None = Form(None),
        language: str = Form("Spanish"),
        transcript: str | None = Form(None),
    ):
        audio = await file.read()
        voice = container.catalog.register(
            audio,
            slug=slug,
            name=name or slug,
            language=language,
            transcript=transcript,
        )
        return {"slug": voice.slug, "name": voice.name, "origin": voice.origin}

    @app.get("/api/voices/{slug}")
    async def show_voice(slug: str):
        voice = container.catalog.get(slug)
        return {
            "slug": voice.slug,
            "name": voice.name,
            "origin": voice.origin,
            "language": voice.language,
            "sample_rate": voice.sample_rate,
            "ref_audio": str(voice.ref_audio),
            "recipe": dict(voice.recipe),
        }

    @app.delete("/api/voices/{slug}", status_code=204)
    async def remove_voice(slug: str):
        container.catalog.remove(slug)

    # ── dialogue ────────────────────────────────────────────────────────
    @app.post("/api/dialogues/render")
    async def render_dialogue(request: RenderRequest):
        dialogue = parse_dialogue(_parse_yaml(request.script))
        out = Path(request.out) if request.out else container.settings.out_dir / "render.wav"
        job = container.queue.submit(
            "render",
            lambda: container.dialogue.render(
                dialogue, out, target_lufs=request.lufs if request.master else None
            ),
        )
        finished = container.queue.wait(job.id, timeout=3600)
        if finished.state != "done":
            raise VoiceForgeError(finished.error or "the render job did not finish")
        result = finished.result
        return {
            "job": job.id,
            "path": str(result.path),
            "duration_s": round(result.duration_s, 2),
            "lines": result.lines,
            "speakers": list(result.speakers),
        }

    # ── engine lifecycle ────────────────────────────────────────────────
    @app.get("/api/engine")
    async def engine_status():
        return dict(container.engine.status())

    @app.post("/api/engine/{action}")
    async def engine_action(action: str):
        if action == "up":
            return dict(container.engine.up())
        if action == "warm":
            return dict(container.engine.warm())
        if action == "down":
            return dict(container.engine.down())
        raise HTTPException(status_code=400, detail=f"unknown action: {action}")

    return app


def _parse_yaml(text: str):
    import yaml

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="script root must be a mapping")
    return data
