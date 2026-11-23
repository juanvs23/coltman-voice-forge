"""HTTP adapter: REST API + a small practical UI.

Swagger at /docs comes free; the legacy page at / and the Gradio console at
/ui are both clients of the same API.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ...application.audition_store import AuditionStore
from ...container import Container
from ...domain.errors import (
    EngineAlreadyRunning,
    EngineBusy,
    EngineUnavailable,
    ValidationError,
    VoiceForgeError,
    VoiceNotFound,
)
from ...domain.models import Emotion, EmotionAxis, VoiceBrief
from ...domain.script import parse_dialogue
from .ui import INDEX_HTML
from .webui import mount_console
from .webui.context import preview_slots


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
    emotional: bool = False


class DesignCandidatesRequest(BaseModel):
    """An audition: model work, no catalog entry."""

    description: str
    language: str = "Spanish"
    candidates: int = 4
    seed: int | None = None
    preview_text: str | None = None
    emotional: bool = False


class DesignRegisterRequest(BaseModel):
    """The second step: register one candidate the audition left on disk."""

    token: str
    slug: str
    pick: int = 0
    name: str | None = None
    tags: list[str] = []
    emotional: bool = False


class PreviewRequest(BaseModel):
    text: str
    axes: dict[str, float] = {}
    intensity: float = 0.6
    hint: str | None = None
    speed: float = 1.0


class DeriveRequest(BaseModel):
    slug: str
    name: str | None = None
    pitch: float = -2.0
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

    # ── previews ────────────────────────────────────────────────────────
    @app.get("/api/previews")
    def list_previews():
        """The three fixed slots, always in order, empty ones included."""
        return preview_slots(container.settings.out_dir)

    # ── voices ──────────────────────────────────────────────────────────
    @app.get("/api/voices")
    def list_voices():
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
    def queue_state():
        return container.queue.snapshot()

    @app.get("/api/runtime")
    def runtime_status():
        return container.runtime.status()

    @app.get("/api/runtime/plan")
    def runtime_plan(backend: str = "auto"):
        return container.runtime.plan(backend).as_dict()

    @app.post("/api/voices/design", status_code=201)
    def design_voice(request: DesignRequest):
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
                neutral=not request.emotional,
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

    @app.post("/api/voices/design/candidates", status_code=201)
    def design_candidates(request: DesignCandidatesRequest):
        """Generate candidates and leave them in ``out/candidates`` for audition.

        Nothing enters the catalog here: the response carries a token the
        operator quotes to ``POST /api/voices/design/register`` once they have
        heard the candidates.
        """
        brief = VoiceBrief(
            description=request.description,
            language=request.language,
            candidates=request.candidates,
            seed=request.seed,
            preview_text=request.preview_text,
        )
        auditions = AuditionStore(container.settings.out_dir)

        def audition():
            candidates = container.catalog.audition(
                brief, neutral=not request.emotional
            )
            return auditions.save(brief, candidates, emotional=request.emotional)

        job = container.queue.submit("design", audition)
        finished = container.queue.wait(job.id, timeout=1800)
        if finished.state != "done":
            raise VoiceForgeError(finished.error or "the audition did not finish")
        return {"job": job.id, **finished.result.payload()}

    @app.post("/api/voices/design/register", status_code=201)
    def design_register(request: DesignRegisterRequest):
        """Register a candidate by token. Paths and recipes stay server-side."""
        auditions = AuditionStore(container.settings.out_dir)
        audition = auditions.load(request.token)
        if not 0 <= request.pick < len(audition.candidates):
            raise ValidationError(
                f"pick must be within 0..{len(audition.candidates) - 1}"
            )
        voice = container.catalog.register_candidate(
            audition.candidates[request.pick],
            brief=audition.brief,
            slug=request.slug,
            name=request.name,
            pick=request.pick,
            tags=tuple(request.tags),
            neutral=not request.emotional,
            total=len(audition.candidates),
        )
        return {
            "voice": {"slug": voice.slug, "name": voice.name, "origin": voice.origin},
            "candidates": len(audition.candidates),
            "picked": request.pick,
        }

    @app.post("/api/voices", status_code=201)
    async def register_voice(
        file: UploadFile = File(...),
        slug: str = Form(...),
        name: str | None = Form(None),
        language: str = Form("Spanish"),
        transcript: str | None = Form(None),
        emotional: bool = Form(False),
    ):
        audio = await file.read()
        # Registering runs ffprobe and writes to disk: keep it off the loop.
        voice = await run_in_threadpool(
            container.catalog.register,
            audio,
            slug=slug,
            name=name or slug,
            language=language,
            transcript=transcript,
            neutral=not emotional,
        )
        return {"slug": voice.slug, "name": voice.name, "origin": voice.origin}

    @app.get("/api/voices/{slug}")
    def show_voice(slug: str):
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
    def remove_voice(slug: str):
        container.catalog.remove(slug)

    @app.post("/api/voices/{slug}/derive", status_code=201)
    def derive_voice(slug: str, request: DeriveRequest):
        voice = container.derive.derive(
            slug,
            slug=request.slug,
            name=request.name,
            pitch_semitones=request.pitch,
            tags=tuple(request.tags),
        )
        return {
            "slug": voice.slug,
            "origin": voice.origin,
            "derived_from": voice.recipe.get("derived_from"),
            "pitch_semitones": voice.recipe.get("pitch_semitones"),
        }

    @app.post("/api/voices/{slug}/preview")
    def preview_voice(slug: str, request: PreviewRequest):
        try:
            emotion = Emotion(
                axes={EmotionAxis(key): value for key, value in request.axes.items()},
                intensity=request.intensity,
                hint=request.hint,
            )
        except ValueError as exc:
            raise VoiceForgeError(f"unknown emotion axis: {exc}") from exc

        job = container.queue.submit(
            "preview",
            lambda: container.preview.preview(
                slug, request.text, emotion=emotion, speed=request.speed
            ),
        )
        finished = container.queue.wait(job.id, timeout=900)
        if finished.state != "done":
            raise VoiceForgeError(finished.error or "the preview did not finish")
        path, duration, slot = finished.result
        return {
            "path": str(path),
            "url": f"/previews/{path.name}",
            "slot": slot,
            "duration_s": round(duration, 2),
        }

    # ── dialogue ────────────────────────────────────────────────────────
    @app.post("/api/dialogues/render")
    def render_dialogue(request: RenderRequest):
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
    def engine_status():
        return dict(container.engine.status())

    @app.post("/api/engine/{action}")
    def engine_action(action: str):
        if action == "up":
            return dict(container.engine.up())
        if action == "warm":
            return dict(container.engine.warm())
        if action == "down":
            return dict(container.engine.down())
        raise HTTPException(status_code=400, detail=f"unknown action: {action}")

    previews = container.settings.out_dir / "previews"
    previews.mkdir(parents=True, exist_ok=True)
    app.mount("/previews", StaticFiles(directory=str(previews)), name="previews")

    candidates = container.settings.out_dir / "candidates"
    candidates.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/candidates", StaticFiles(directory=str(candidates)), name="candidates"
    )

    # The console replaces nothing yet: `/` stays on the legacy page until the
    # console reaches parity in the last slice.
    mount_console(app, container, path="/ui")

    return app


def _parse_yaml(text: str):
    import yaml

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="script root must be a mapping")
    return data
