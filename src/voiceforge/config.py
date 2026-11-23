"""Settings. Everything overridable by environment, nothing hardcoded to a path."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_runtime_lib() -> Path | None:
    """A CUDA build made against the local cuFFT prefix needs it at run time."""
    from_env = os.getenv("VOICEFORGE_RUNTIME_LIB")
    if from_env:
        return Path(from_env)
    candidate = PROJECT_ROOT / "dist" / "cuda" / "usr" / "lib64"
    return candidate if candidate.is_dir() else None


@dataclass(frozen=True)
class Settings:
    catalog_dir: Path = field(default_factory=lambda: Path(os.getenv("VOICEFORGE_CATALOG", "catalog")))
    out_dir: Path = field(default_factory=lambda: Path(os.getenv("VOICEFORGE_OUT", "out")))
    work_dir: Path = field(default_factory=lambda: Path(os.getenv("VOICEFORGE_WORK", "out/.work")))
    engine_url: str = field(default_factory=lambda: os.getenv("VOICEFORGE_ENGINE_URL", "http://127.0.0.1:8710"))
    engine_python: str = field(
        default_factory=lambda: os.getenv(
            "VOICEFORGE_ENGINE_PYTHON", "python3"
        )
    )
    engine_script: Path = field(
        default_factory=lambda: Path(
            os.getenv("VOICEFORGE_ENGINE_SCRIPT", str(PROJECT_ROOT / "engines" / "qwen_host.py"))
        )
    )
    default_lufs: float = field(default_factory=lambda: float(os.getenv("VOICEFORGE_LUFS", "-14")))
    api_host: str = field(default_factory=lambda: os.getenv("VOICEFORGE_API_HOST", "127.0.0.1"))
    api_port: int = field(default_factory=lambda: int(os.getenv("VOICEFORGE_API_PORT", "8720")))
    dist_dir: Path = field(default_factory=lambda: Path(os.getenv("VOICEFORGE_DIST", "dist")))
    runtime_repo: str = field(
        default_factory=lambda: os.getenv(
            "VOICEFORGE_RUNTIME_REPO", "https://github.com/0xShug0/audio.cpp"
        )
    )
    runtime_revision: str = field(
        default_factory=lambda: os.getenv("VOICEFORGE_RUNTIME_REVISION", "main")
    )
    # Which adapter pair is wired: "audiocpp" (GGUF, no torch) or "qwen".
    adapter: str = field(default_factory=lambda: os.getenv("VOICEFORGE_ADAPTER", "audiocpp"))
    # How the audiocpp adapter talks to the runtime: "server" keeps the model
    # resident; "cli" spawns one process per call.
    transport: str = field(default_factory=lambda: os.getenv("VOICEFORGE_TRANSPORT", "server"))
    audiocpp_port: int = field(default_factory=lambda: int(os.getenv("VOICEFORGE_AUDIOCCP_PORT", "8731")))
    # Device backend handed to the runtime: cpu | cuda | vulkan | hip | metal.
    device: str = field(default_factory=lambda: os.getenv("VOICEFORGE_DEVICE", "cuda"))
    # Extra library path for a CUDA build linked against a local cuFFT prefix.
    runtime_lib_path: Path | None = field(default_factory=_default_runtime_lib)
    runtime_bin: Path = field(
        default_factory=lambda: Path(
            os.getenv("VOICEFORGE_RUNTIME_BIN", str(PROJECT_ROOT / "dist" / "bin" / "audiocpp_cli"))
        )
    )
    server_bin: Path = field(
        default_factory=lambda: Path(
            os.getenv("VOICEFORGE_SERVER_BIN", str(PROJECT_ROOT / "dist" / "bin" / "audiocpp_server"))
        )
    )
    model_path: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "VOICEFORGE_MODEL",
                str(PROJECT_ROOT / "models" / "ming3" / "ming-3.0-tts-0.5b-q8_0.gguf"),
            )
        )
    )
    timbre_model_path: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "VOICEFORGE_TIMBRE_MODEL",
                str(
                    PROJECT_ROOT
                    / "models"
                    / "tone-color-vc"
                    / "tone-color-vc-f16.gguf"
                ),
            )
        )
    )

    def normalised(self) -> "Settings":
        return Settings(
            catalog_dir=self.catalog_dir.expanduser().resolve(),
            out_dir=self.out_dir.expanduser().resolve(),
            work_dir=self.work_dir.expanduser().resolve(),
            engine_url=self.engine_url,
            engine_python=self.engine_python,
            engine_script=self.engine_script.expanduser().resolve(),
            default_lufs=self.default_lufs,
            api_host=self.api_host,
            api_port=self.api_port,
            dist_dir=self.dist_dir.expanduser().resolve(),
            runtime_repo=self.runtime_repo,
            runtime_revision=self.runtime_revision,
            adapter=self.adapter,
            transport=self.transport,
            audiocpp_port=self.audiocpp_port,
            device=self.device,
            runtime_lib_path=(
                self.runtime_lib_path.expanduser().resolve()
                if self.runtime_lib_path
                else None
            ),
            runtime_bin=self.runtime_bin.expanduser().resolve(),
            server_bin=self.server_bin.expanduser().resolve(),
            model_path=self.model_path.expanduser().resolve(),
            timbre_model_path=self.timbre_model_path.expanduser().resolve(),
        )
