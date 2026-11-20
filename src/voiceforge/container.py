"""Wiring. The only place where concrete adapters meet the use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .adapters.secondary.engine_http import HttpEngine
from .adapters.secondary.engine_process import EngineSupervisor
from .adapters.secondary.ffmpeg_assembler import FfmpegAssembler
from .adapters.secondary.fs_catalog import FileCatalog
from .application.catalog_service import CatalogService
from .application.dialogue_service import DialogueService
from .config import Settings


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Container:
    settings: Settings
    catalog: CatalogService
    dialogue: DialogueService
    engine: EngineSupervisor


def build(settings: Settings | None = None) -> Container:
    settings = (settings or Settings()).normalised()

    repository = FileCatalog(settings.catalog_dir)
    http_engine = HttpEngine(settings.engine_url)
    supervisor = EngineSupervisor(
        python_exe=settings.engine_python,
        script=settings.engine_script,
        base_url=settings.engine_url,
        log_path=settings.out_dir / "engine.log",
        pid_path=settings.out_dir / "engine.pid",
    )

    return Container(
        settings=settings,
        catalog=CatalogService(repository, http_engine, _now),
        dialogue=DialogueService(
            repository, http_engine, FfmpegAssembler(), settings.work_dir
        ),
        engine=supervisor,
    )
