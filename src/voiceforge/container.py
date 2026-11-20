"""Wiring. The only place where concrete adapters meet the use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .adapters.secondary.audiocpp_cli import AudiocppCli, AudiocppControl
from .adapters.secondary.audiocpp_server import AudiocppServer, AudiocppServerControl
from .adapters.secondary.engine_http import HttpEngine
from .adapters.secondary.engine_process import EngineSupervisor
from .adapters.secondary.ffmpeg_assembler import FfmpegAssembler
from .adapters.secondary.fs_catalog import FileCatalog
from .adapters.secondary.runtime_builder import RuntimeBuilder
from .application.catalog_service import CatalogService
from .application.dialogue_service import DialogueService
from .application.queue import SerialQueue
from .config import Settings


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Container:
    settings: Settings
    catalog: CatalogService
    dialogue: DialogueService
    engine: object  # EngineControl
    queue: SerialQueue
    runtime: RuntimeBuilder


def build(settings: Settings | None = None) -> Container:
    settings = (settings or Settings()).normalised()

    repository = FileCatalog(settings.catalog_dir)
    work_queue = SerialQueue()

    if settings.adapter == "audiocpp" and settings.transport == "server":
        # Resident model: one load, many lines.
        designer = synthesizer = AudiocppServer(f"http://127.0.0.1:{settings.audiocpp_port}")
        engine = AudiocppServerControl(
            settings.server_bin,
            settings.model_path,
            backend=settings.device,
            port=settings.audiocpp_port,
            config_path=settings.out_dir / "server.json",
            log_path=settings.out_dir / "server.log",
        )
    elif settings.adapter == "audiocpp":
        # GGUF runtime, one process per call: no Python model stack.
        designer = synthesizer = AudiocppCli(
            binary=settings.runtime_bin,
            model=settings.model_path,
            backend=settings.device,
        )
        engine = AudiocppControl(settings.runtime_bin, settings.model_path, settings.device)
    elif settings.adapter == "qwen":
        http_engine = HttpEngine(settings.engine_url)
        designer = synthesizer = http_engine
        engine = EngineSupervisor(
            python_exe=settings.engine_python,
            script=settings.engine_script,
            base_url=settings.engine_url,
            log_path=settings.out_dir / "engine.log",
            pid_path=settings.out_dir / "engine.pid",
            lock_path=settings.out_dir / "engine.lock",
            busy=lambda: bool(work_queue.snapshot()["busy"]),
        )
    else:
        raise ValueError(f"unknown adapter {settings.adapter!r}; expected audiocpp or qwen")

    return Container(
        settings=settings,
        catalog=CatalogService(repository, designer, _now),
        dialogue=DialogueService(repository, synthesizer, FfmpegAssembler(), settings.work_dir),
        engine=engine,
        queue=work_queue,
        runtime=RuntimeBuilder(
            dist_dir=settings.dist_dir,
            repo_url=settings.runtime_repo,
            revision=settings.runtime_revision,
        ),
    )
