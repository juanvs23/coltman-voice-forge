"""Runtime bootstrap: detection matrix, plan, idempotency. No GPU, no compiler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from voiceforge.adapters.secondary import runtime_builder as rb
from voiceforge.domain.errors import BuildFailed


def hardware(**kwargs) -> rb.Hardware:
    defaults = dict(os="linux", nvidia=False, cuda_toolkit=None, cuda_arch=None, vulkan=False)
    defaults.update(kwargs)
    return rb.Hardware(**defaults)


def test_nvidia_with_toolkit_chooses_cuda():
    backend, reason = rb.choose_backend(hardware(nvidia=True, cuda_toolkit="13.2", vulkan=True))
    assert backend == "cuda"
    assert "NVIDIA" in reason


def test_nvidia_without_toolkit_falls_back_to_vulkan():
    backend, reason = rb.choose_backend(hardware(nvidia=True, cuda_toolkit=None, vulkan=True))
    assert backend == "vulkan"
    assert "no CUDA toolkit" in reason


def test_no_gpu_falls_back_to_cpu():
    backend, reason = rb.choose_backend(hardware())
    assert backend == "cpu"
    assert "portable CPU" in reason


def test_explicit_cuda_without_hardware_is_an_error():
    with pytest.raises(BuildFailed):
        rb.choose_backend(hardware(vulkan=True), "cuda")


def test_explicit_vulkan_without_driver_is_an_error():
    with pytest.raises(BuildFailed):
        rb.choose_backend(hardware(), "vulkan")


def test_unknown_backend_is_rejected():
    with pytest.raises(BuildFailed):
        rb.choose_backend(hardware(), "opencl")


def test_cmake_flags_use_the_real_engine_switches():
    assert rb.cmake_flags("cuda", hardware(cuda_arch="89")) == (
        "-DENGINE_ENABLE_CUDA=ON",
        "-DCMAKE_CUDA_ARCHITECTURES=89",
    )
    assert rb.cmake_flags("vulkan", hardware(vulkan=True)) == ("-DENGINE_ENABLE_VULKAN=ON",)
    assert rb.cmake_flags("cpu", hardware()) == ()


def test_probe_reads_nvidia_and_cuda_version():
    calls = []

    def runner(command, cwd):
        calls.append(command[0])
        if command[0] == "nvidia-smi" and "-L" in command:
            return 0, "GPU 0: NVIDIA GeForce RTX 4060 Laptop GPU (UUID: x)"
        if command[0] == "nvidia-smi":
            return 0, "8.9\n"
        if command[0] == "nvcc":
            return 0, "Cuda compilation tools, release 13.2, V13.2.51"
        return 1, ""

    probe = rb.HardwareProbe(
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        exists=lambda path: path == "/usr/local/cuda/lib64/libcufft.so",
    )
    detected = probe.detect()

    assert detected.nvidia is True
    assert detected.cuda_toolkit == "13.2"
    assert detected.cuda_arch == "89"
    assert detected.cuda_root == "/usr/local/cuda"
    assert "nvidia-smi" in calls


def test_nvcc_without_cufft_is_not_a_usable_toolkit():
    """The false positive that broke the first build: compiler without libraries."""

    def runner(command, cwd):
        if command[0] == "nvidia-smi":
            return 0, "GPU 0: NVIDIA GeForce RTX 4060 Laptop GPU"
        if command[0] == "nvcc":
            return 0, "Cuda compilation tools, release 13.2, V13.2.51"
        return 1, ""

    probe = rb.HardwareProbe(
        runner=runner,
        which=lambda name: f"/usr/bin/{name}",
        exists=lambda _: False,  # no libcufft anywhere
    )
    detected = probe.detect()

    assert detected.nvidia is True
    assert detected.cuda_toolkit is None
    assert rb.choose_backend(detected)[0] == "cpu"


def test_vulkan_needs_headers_and_a_shader_compiler():
    probe = rb.HardwareProbe(
        runner=lambda command, cwd: (0, "libvulkan.so.1 (libc6,x86-64)"),
        which=lambda name: "/usr/bin/glslc" if name == "glslc" else None,
        exists=lambda path: path == "/usr/include/vulkan/vulkan.h",
    )
    assert probe.detect().vulkan is True

    no_headers = rb.HardwareProbe(
        runner=lambda command, cwd: (0, "libvulkan.so.1"),
        which=lambda name: "/usr/bin/glslc",
        exists=lambda _: False,
    )
    assert no_headers.detect().vulkan is False


def test_probe_without_tools_reports_nothing():
    probe = rb.HardwareProbe(runner=lambda command, cwd: (127, ""), which=lambda name: None, exists=lambda _: False)
    detected = probe.detect()
    assert detected.nvidia is False
    assert detected.cuda_toolkit is None
    assert detected.vulkan is False


class FakeProbe:
    def __init__(self, hw):
        self.hw = hw

    def detect(self):
        return self.hw


class RecordingRunner:
    def __init__(self, results=None):
        self.commands: list[list[str]] = []
        self.results = results or {}

    def __call__(self, command, cwd):
        self.commands.append(list(command))
        joined = " ".join(command)
        for needle, result in self.results.items():
            if needle in joined:
                return result
        return 0, ""


def test_plan_is_reported_without_building(tmp_path):
    builder = rb.RuntimeBuilder(
        dist_dir=tmp_path / "dist",
        probe=FakeProbe(hardware(nvidia=True, cuda_toolkit="13.2", cuda_arch="89")),
        runner=RecordingRunner(),
    )
    plan = builder.plan()
    assert plan.backend == "cuda"
    assert plan.bin_dir == tmp_path / "dist" / "bin"
    assert not (tmp_path / "dist").exists()


def test_build_is_idempotent_when_the_manifest_matches(tmp_path):
    dist = tmp_path / "dist"
    (dist / "bin").mkdir(parents=True)
    for target in rb.TARGETS:
        binary = dist / "bin" / target
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
    (dist / "BUILD.json").write_text(
        json.dumps({"backend": "cuda", "binaries": {t: True for t in rb.TARGETS}}),
        encoding="utf-8",
    )

    runner = RecordingRunner()
    builder = rb.RuntimeBuilder(
        dist_dir=dist,
        probe=FakeProbe(hardware(nvidia=True, cuda_toolkit="13.2")),
        runner=runner,
    )
    result = builder.build()

    assert result["action"] == "already-built"
    assert runner.commands == []


def test_build_runs_cmake_with_the_chosen_backend(tmp_path):
    dist = tmp_path / "dist"
    source = dist / "src" / "audio.cpp"
    source.mkdir(parents=True)

    def runner(command, cwd):
        runner.commands.append(list(command))
        if command[0] == "cmake" and "--build" in command:
            for target in rb.TARGETS:
                binary = dist / "build" / target
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text("#!/bin/sh\n")
                binary.chmod(0o755)
        if command[:3] == ["git", "-C", str(source)]:
            return 0, "abc1234\n"
        return 0, ""

    runner.commands = []
    builder = rb.RuntimeBuilder(
        dist_dir=dist,
        probe=FakeProbe(hardware(vulkan=True)),
        runner=runner,
    )
    result = builder.build()

    configure = next(cmd for cmd in runner.commands if "-DENGINE_ENABLE_VULKAN=ON" in cmd)
    assert configure[0] == "cmake"
    assert result["backend"] == "vulkan"
    assert (dist / "bin" / "audiocpp_cli").exists()
    assert any(cmd[0] == "strip" for cmd in runner.commands), "binaries must be stripped"
    manifest = json.loads((dist / "BUILD.json").read_text())
    assert manifest["backend"] == "vulkan"
    assert manifest["revision"] == "abc1234"


def test_stale_build_dir_with_another_backend_is_wiped(tmp_path):
    dist = tmp_path / "dist"
    (dist / "src" / "audio.cpp").mkdir(parents=True)
    stale = dist / "build"
    stale.mkdir()
    (stale / "CMakeCache.txt").write_text("ENGINE_ENABLE_CUDA:BOOL=ON\n")
    (stale / ".voiceforge-backend").write_text("cuda")

    commands: list[list[str]] = []

    def runner(command, cwd):
        commands.append(list(command))
        if command[0] == "cmake" and "--build" in command:
            for target in rb.TARGETS:
                binary = dist / "build" / target
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text("#!/bin/sh\n")
                binary.chmod(0o755)
        return 0, "abc1234\n" if "rev-parse" in command else ""

    builder = rb.RuntimeBuilder(
        dist_dir=dist,
        probe=FakeProbe(hardware()),
        runner=runner,
    )
    result = builder.build()

    assert result["backend"] == "cpu"
    assert not (stale / "CMakeCache.txt").exists()
    assert (stale / ".voiceforge-backend").read_text() == "cpu"


def test_failed_configure_raises_with_context(tmp_path):
    dist = tmp_path / "dist"
    (dist / "src" / "audio.cpp").mkdir(parents=True)  # skip the clone step

    builder = rb.RuntimeBuilder(
        dist_dir=dist,
        probe=FakeProbe(hardware()),
        runner=lambda command, cwd: (2, "CMake Error: no compiler found"),
    )
    with pytest.raises(BuildFailed) as exc:
        builder.build()
    assert "cmake configure failed" in str(exc.value)
    assert "no compiler found" in str(exc.value)
