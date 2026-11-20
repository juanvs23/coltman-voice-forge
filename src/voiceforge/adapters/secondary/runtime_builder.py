"""Runtime bootstrap: detect the machine, choose a backend, build into dist/.

Why this exists: the model runtime is the only compiled piece of the system, and
building it by hand is exactly the kind of step that rots. The rule here is
"decide from evidence, record the decision, never rebuild blindly".

Everything is injectable (probe + runner) so the whole decision matrix is
testable without a GPU, a compiler or a network.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from ...domain.errors import BuildFailed

BACKENDS = ("cuda", "vulkan", "cpu")
TARGETS = ("audiocpp_cli", "audiocpp_server")

Runner = Callable[[Sequence[str], Path | None], tuple[int, str]]


# ── detection ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Hardware:
    os: str
    nvidia: bool = False
    cuda_toolkit: str | None = None
    cuda_root: str | None = None
    cuda_arch: str | None = None
    vulkan: bool = False

    @property
    def summary(self) -> str:
        bits = [self.os]
        bits.append("nvidia" if self.nvidia else "no-nvidia")
        bits.append(f"cuda {self.cuda_toolkit}" if self.cuda_toolkit else "no-usable-cuda")
        bits.append("vulkan" if self.vulkan else "no-vulkan")
        return " · ".join(bits)


class HardwareProbe:
    """Reads the machine. Never changes anything."""

    def __init__(
        self,
        runner: Runner | None = None,
        which: Callable[[str], str | None] = shutil.which,
        exists: Callable[[str], bool] = os.path.exists,
    ):
        self._run = runner or _run
        self._which = which
        self._exists = exists

    def detect(self) -> Hardware:
        cuda_version, cuda_root = self._usable_cuda()
        return Hardware(
            os=platform.system().lower(),
            nvidia=self._has_nvidia(),
            cuda_toolkit=cuda_version,
            cuda_root=cuda_root,
            cuda_arch=self._cuda_arch() if cuda_version else None,
            vulkan=self._buildable_vulkan(),
        )

    # ── probes ──────────────────────────────────────────────────────────
    def _has_nvidia(self) -> bool:
        if self._exists("/proc/driver/nvidia/version"):
            return True
        if not self._which("nvidia-smi"):
            return False
        code, out = self._run(["nvidia-smi", "-L"], None)
        return code == 0 and "GPU" in out

    def _usable_cuda(self) -> tuple[str | None, str | None]:
        """A toolkit is only usable when the *libraries* exist, not just nvcc.

        `nvcc` in /usr/bin without libcufft is the classic false positive: the
        distro ships the compiler, CMake finds CUDAToolkit, and the build dies
        at ``CUDA::cufft``.
        """
        if not self._which("nvcc"):
            return None, None
        root = self._cuda_root()
        if root is None:
            return None, None
        code, out = self._run(["nvcc", "--version"], None)
        if code != 0:
            return None, None
        version = "unknown"
        for line in out.splitlines():
            if "release" in line:
                version = line.split("release", 1)[1].strip().split(",")[0].strip()
                break
        return version, root

    def _cuda_root(self) -> str | None:
        candidates = [
            os.environ.get("CUDAToolkit_ROOT"),
            os.environ.get("CUDA_HOME"),
            "/usr/local/cuda",
            "/usr/local/cuda-13.2",
            "/usr/local/cuda-12.9",
        ]
        for candidate in candidates:
            if candidate and self._exists(f"{candidate}/lib64/libcufft.so"):
                return candidate
        if self._exists("/usr/lib/x86_64-linux-gnu/libcufft.so"):
            return "/usr"
        return None

    def _cuda_arch(self) -> str | None:
        if not self._which("nvidia-smi"):
            return None
        code, out = self._run(
            ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"], None
        )
        if code != 0 or not out.strip():
            return None
        first = out.strip().splitlines()[0].strip()
        compact = first.replace(".", "")
        return compact if compact.isdigit() else None

    def _buildable_vulkan(self) -> bool:
        """Runtime alone is not enough: the build needs headers and a shader compiler."""
        if not (
            self._exists("/usr/include/vulkan/vulkan.h")
            or self._exists("/usr/local/include/vulkan/vulkan.h")
        ):
            return False
        if not (self._which("glslc") or self._which("glslangValidator")):
            return False
        code, out = self._run(["ldconfig", "-p"], None)
        return code == 0 and "libvulkan.so" in out


# ── plan ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class BuildPlan:
    backend: str
    reason: str
    hardware: Hardware
    source_dir: Path
    build_dir: Path
    bin_dir: Path
    cmake_flags: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["hardware"] = asdict(self.hardware)
        for key in ("source_dir", "build_dir", "bin_dir"):
            data[key] = str(data[key])
        data["cmake_flags"] = list(self.cmake_flags)
        return data


def choose_backend(hardware: Hardware, requested: str = "auto") -> tuple[str, str]:
    """The decision, in one place, with the reason attached."""

    if requested not in ("auto", *BACKENDS):
        raise BuildFailed(f"unknown backend {requested!r}; expected auto, cuda, vulkan or cpu")

    if requested == "cuda":
        if not (hardware.nvidia and hardware.cuda_toolkit):
            raise BuildFailed(
                "CUDA was requested but this machine has no NVIDIA GPU with a CUDA toolkit"
            )
        return "cuda", "explicitly requested"
    if requested == "vulkan":
        if not hardware.vulkan:
            raise BuildFailed("Vulkan was requested but no Vulkan driver/tooling was found")
        return "vulkan", "explicitly requested"
    if requested == "cpu":
        return "cpu", "explicitly requested"

    if hardware.nvidia and hardware.cuda_toolkit:
        return "cuda", "NVIDIA GPU and CUDA toolkit detected"
    if hardware.vulkan:
        return "vulkan", "no CUDA toolkit, Vulkan available"
    return "cpu", "no GPU backend tooling found; portable CPU kernels"


def cmake_flags(backend: str, hardware: Hardware) -> tuple[str, ...]:
    if backend == "cuda":
        flags = ["-DENGINE_ENABLE_CUDA=ON"]
        root = hardware.cuda_root
        if root and root != "/usr":
            # The provider's docs are explicit: set both, a distro CUDA in PATH
            # otherwise wins and the build links the wrong runtime.
            flags.append(f"-DCUDAToolkit_ROOT={root}")
            flags.append(f"-DCMAKE_CUDA_COMPILER={root}/bin/nvcc")
        if hardware.cuda_arch:
            flags.append(f"-DCMAKE_CUDA_ARCHITECTURES={hardware.cuda_arch}")
        else:
            flags.append("-DCMAKE_CUDA_ARCHITECTURES=native")
        return tuple(flags)
    if backend == "vulkan":
        return ("-DENGINE_ENABLE_VULKAN=ON",)
    return ()


# ── builder ─────────────────────────────────────────────────────────────
class RuntimeBuilder:
    def __init__(
        self,
        dist_dir: Path,
        repo_url: str = "https://github.com/0xShug0/audio.cpp",
        revision: str = "main",
        probe: HardwareProbe | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.dist = Path(dist_dir)
        self.repo_url = repo_url
        self.revision = revision
        self.probe = probe or HardwareProbe()
        self._run = runner or _run
        self.source = self.dist / "src" / "audio.cpp"
        self.build_dir = self.dist / "build"
        self.bin_dir = self.dist / "bin"
        self.manifest = self.dist / "BUILD.json"

    # ── read ────────────────────────────────────────────────────────────
    def status(self) -> dict:
        if not self.manifest.exists():
            return {"built": False, "dist": str(self.dist)}
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["built"] = True
        data["binaries"] = {
            name: (self.bin_dir / name).exists() for name in TARGETS
        }
        return data

    def plan(self, requested: str = "auto") -> BuildPlan:
        hardware = self.probe.detect()
        backend, reason = choose_backend(hardware, requested)
        return BuildPlan(
            backend=backend,
            reason=reason,
            hardware=hardware,
            source_dir=self.source,
            build_dir=self.build_dir,
            bin_dir=self.bin_dir,
            cmake_flags=cmake_flags(backend, hardware),
        )

    # ── write ───────────────────────────────────────────────────────────
    def build(self, requested: str = "auto", force: bool = False, jobs: int | None = None) -> dict:
        plan = self.plan(requested)
        current = self.status()
        if (
            not force
            and current["built"]
            and current.get("backend") == plan.backend
            and all(current["binaries"].values())
        ):
            return {**current, "action": "already-built"}

        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.build_dir.parent.mkdir(parents=True, exist_ok=True)
        self._fetch_source()

        configure = [
            "cmake", "-S", str(self.source), "-B", str(self.build_dir),
            "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
            *plan.cmake_flags,
        ]
        self._must(configure, "cmake configure failed")

        build = [
            "cmake", "--build", str(self.build_dir),
            "-j", str(jobs or max(1, (os.cpu_count() or 2) - 1)),
            *(f"--target={target}" for target in TARGETS),
        ]
        self._must(build, "cmake build failed")

        copied = []
        for target in TARGETS:
            for candidate in self.build_dir.rglob(target):
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    destination = self.bin_dir / target
                    shutil.copy2(candidate, destination)
                    copied.append(str(destination))
                    break

        data = {
            "backend": plan.backend,
            "reason": plan.reason,
            "hardware": asdict(plan.hardware),
            "cmake_flags": list(plan.cmake_flags),
            "repo": self.repo_url,
            "revision": self._resolved_revision(),
            "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "binaries": {Path(path).name: True for path in copied},
            "action": "built",
        }
        self.manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {**data, "built": True, "dist": str(self.dist)}

    # ── internals ───────────────────────────────────────────────────────
    def _fetch_source(self) -> None:
        self.source.parent.mkdir(parents=True, exist_ok=True)
        if self.source.exists():
            return
        self._must(
            ["git", "clone", "--depth", "1", "--branch", self.revision, self.repo_url, str(self.source)],
            "could not fetch the audio.cpp sources",
        )

    def _resolved_revision(self) -> str:
        code, out = self._run(["git", "-C", str(self.source), "rev-parse", "HEAD"], self.source)
        return out.strip() if code == 0 and out.strip() else self.revision

    def _must(self, command: Sequence[str], message: str) -> None:
        code, out = self._run(list(command), None)
        if code != 0:
            tail = out.strip().splitlines()[-8:]
            raise BuildFailed(f"{message}: {' | '.join(tail)}")


def _run(command: Sequence[str], cwd: Path | None) -> tuple[int, str]:
    try:
        result = subprocess.run(  # noqa: S603 - fixed local commands
            list(command), cwd=cwd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:
        return 127, str(exc)
    return result.returncode, (result.stdout or "") + (result.stderr or "")
