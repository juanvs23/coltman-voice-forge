"""audio.cpp server adapter: the model stays resident.

Why this exists next to the CLI adapter: the CLI pays a model load per call.
The server loads once and answers `/v1/audio/speech`, so narration stops paying
for startup. Measured on CPU: ~6.9 s per short line either way *after* warm-up,
versus ~12 s through the CLI — the difference is the load, not the model.

Contract used here was discovered empirically against `audiocpp_server` and is
covered by tests; it is not guessed:

    POST /v1/audio/speech
    {"model": "<entry id>", "input": "<text>", "voice": "<reference path>",
     "options": {"language": "es", "template_name": "freeform",
                 "instruct": "...", "reference_text": "...", "seed": 1895}}
    -> 200 with a WAV body
"""

from __future__ import annotations

import io
import json
import os
import secrets
import signal
import subprocess
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

import httpx

from ...domain.errors import EngineAlreadyRunning, EngineBusy, EngineUnavailable
from ...domain.models import DesignCandidate, Emotion, Voice, VoiceBrief
from .audiocpp_cli import DEFAULT_PREVIEW, _lang, build_instruct
from .pid_signal import (
    TOKEN_ENV,
    PidfdUnavailable,
    ProcessGone,
    identity_matches,
    open_process,
)

DESIGN_MODEL_ID = "ming-vdes"
SPEECH_MODEL_ID = "ming-tts"


def server_config(model: Path, design_id: str = DESIGN_MODEL_ID, speech_id: str = SPEECH_MODEL_ID) -> dict:
    """Two entries over the same GGUF: one designs, one performs."""
    entry = {"family": "ming3_tts", "mode": "offline", "path": str(model)}
    return {
        "models": [
            {"id": speech_id, "task": "tts", **entry},
            {"id": design_id, "task": "vdes", **entry},
        ]
    }


class AudiocppServer:
    """VoiceDesigner + SpeechSynthesizer over the resident server."""

    def __init__(self, base_url: str = "http://127.0.0.1:8731", timeout_s: float = 900.0, client=None):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._client = client

    # ── ports ───────────────────────────────────────────────────────────
    def design(self, brief: VoiceBrief) -> Sequence[DesignCandidate]:
        preview = brief.preview_text or DEFAULT_PREVIEW
        base_seed = brief.seed if brief.seed is not None else 1895
        candidates: list[DesignCandidate] = []

        for index in range(brief.candidates):
            seed = base_seed + index
            audio = self._speech(
                model=DESIGN_MODEL_ID,
                text=preview,
                options={
                    "language": _lang(brief.language),
                    "instruct": brief.description,
                    "seed": seed,
                },
            )
            candidates.append(
                DesignCandidate(
                    index=index,
                    audio=audio,
                    sample_rate=_wav_rate(audio),
                    recipe={
                        "task": "vdes",
                        "transport": "server",
                        "instruct": brief.description,
                        "preview_text": preview,
                        "language": brief.language,
                        "seed": seed,
                    },
                )
            )
        return candidates

    def synthesize(
        self,
        *,
        text: str,
        voice: Voice,
        emotion: Emotion,
        speed: float,
        out_path: Path,
    ) -> float:
        instruct = build_instruct(emotion, speed)
        options: dict[str, object] = {"language": _lang(voice.language)}
        # Deliberately no `reference_text`: it enables the acoustic-prefix (ICL)
        # mode, which measured 22 s and produced 5.1 s of audio for a 2.6 s line
        # (the model continues the reference). Speaker-only conditioning is 9.5 s
        # and the right length; identity lives in the speaker, performance in
        # the instruction.
        if instruct:
            options["template_name"] = "freeform"
            options["instruct"] = instruct
        seed = voice.recipe.get("seed")
        if isinstance(seed, int):
            options["seed"] = seed

        audio = self._speech(
            model=SPEECH_MODEL_ID,
            text=text,
            voice=str(voice.ref_audio),
            options=options,
        )
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(audio)
        return _wav_duration(audio)

    # ── internals ───────────────────────────────────────────────────────
    def _speech(self, *, model: str, text: str, options: Mapping[str, object], voice: str | None = None) -> bytes:
        payload: dict[str, object] = {"model": model, "input": text, "options": dict(options)}
        if voice:
            # The server field is `voice_ref` (path string, or {type,path|data}).
            payload["voice_ref"] = voice
        try:
            client = self._client or httpx.Client(timeout=self._timeout)
            try:
                response = client.post(f"{self.base_url}/v1/audio/speech", json=payload)
            finally:
                if self._client is None:
                    client.close()
        except httpx.HTTPError as exc:
            raise EngineUnavailable(f"audio.cpp server did not answer: {exc}") from exc

        if response.status_code != 200:
            raise EngineUnavailable(
                f"audio.cpp server rejected the request ({response.status_code}): "
                f"{response.text[:300]}"
            )
        if not response.content:
            raise EngineUnavailable("audio.cpp server returned an empty body")
        return response.content


class AudiocppServerControl:
    """Real on / warm / off for the resident server.

    The process id is persisted in ``pid_path`` as JSON
    ``{"pid": <int>, "port": <int>, "token": <hex>, "started_at": <iso8601>}``.
    That file is a *hint*, not the truth: it can outlive a server that crashed,
    and the kernel recycles pids. Ownership needs two facts, both checked before
    any signal: a pidfd pins the process currently holding the number (see
    ``pid_signal``), and the boot token written into its environment proves that
    process is the one we started. A recycled pid was never given the token, so
    it is rejected without being touched. The file is removed once ``down`` has
    stopped the process, or when it turns out to be garbage.
    """

    def __init__(
        self,
        binary: Path,
        model: Path,
        *,
        backend: str = "cpu",
        port: int = 8731,
        config_path: Path,
        log_path: Path,
        pid_path: Path,
        boot_timeout_s: float = 180.0,
        env: Mapping[str, str] | None = None,
        busy: Callable[[], bool] = lambda: False,
    ) -> None:
        self._binary = Path(binary)
        self._model = Path(model)
        self._backend = backend
        self._port = port
        self._config_path = Path(config_path)
        self._log_path = Path(log_path)
        self._pid_path = Path(pid_path)
        self._boot_timeout = boot_timeout_s
        self._env = dict(env or {})
        self._busy = busy
        self._base_url = f"http://127.0.0.1:{port}"

    def up(self) -> Mapping[str, object]:
        if self._healthy():
            raise EngineAlreadyRunning("the audio.cpp server is already running")
        if not self._binary.exists():
            raise EngineUnavailable(f"runtime binary not found: {self._binary}")

        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(server_config(self._model), indent=2) + "\n", encoding="utf-8"
        )
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self._log_path, "ab")
        token = secrets.token_hex(8)
        process = subprocess.Popen(  # noqa: S603 - fixed local binary
            [
                str(self._binary),
                "--config", str(self._config_path),
                "--backend", self._backend,
                "--port", str(self._port),
                "--no-ui",
                "--max-loaded-models", "1",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, **self._env, TOKEN_ENV: token},
        )
        self._write_pid(process.pid, token)
        deadline = time.monotonic() + self._boot_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._pid_path.unlink(missing_ok=True)
                raise EngineUnavailable(
                    f"audio.cpp server exited with {process.returncode}; see {self._log_path}"
                )
            if self._healthy():
                return {"status": "up", "pid": process.pid, "url": self._base_url}
            time.sleep(1.0)
        raise EngineUnavailable(f"server did not answer within {self._boot_timeout:.0f}s")

    def warm(self, modes: Sequence[str] | None = None) -> Mapping[str, object]:
        """Load the speech entry by doing the smallest possible synthesis."""
        if not self._healthy():
            raise EngineUnavailable("server is down; run `voice-forge up` first")
        started = time.monotonic()
        client = httpx.Client(timeout=600)
        try:
            response = client.post(
                f"{self._base_url}/v1/audio/speech",
                json={"model": SPEECH_MODEL_ID, "input": "Hola.", "options": {"language": "es"}},
            )
        finally:
            client.close()
        if response.status_code != 200:
            raise EngineUnavailable(f"warm-up failed: {response.status_code} {response.text[:200]}")
        return {
            "warmed": True,
            "seconds": round(time.monotonic() - started, 1),
            "url": self._base_url,
        }

    def status(self) -> Mapping[str, object]:
        if not self._healthy():
            return {"status": "down", "url": self._base_url}
        return {"status": "up", "url": self._base_url, "backend": self._backend}

    def down(self, *, force: bool = False) -> Mapping[str, object]:
        """Stop the server this control started, and only that process.

        Refuses while a job is running unless ``force``. A graceful stop over the
        port we already own is preferred: when the runtime exposes ``/shutdown``
        and it makes ``/health`` go quiet, no signal is needed at all. (audio.cpp
        today answers 404 there, so the signal path is the normal one; the wait
        only happens when the endpoint acknowledges.) Otherwise the pid file's pid is
        *verified* before it is signalled — pidfd for the process currently
        holding the number, boot token for ownership — and the whole
        TERM → wait → KILL sequence runs on that one handle. A recycled pid has
        the wrong token and is never touched.
        """
        if self._busy() and not force:
            raise EngineBusy(
                "a job is running; wait for it or use `down --force` to discard it"
            )
        pid, token = self._read_pid()
        healthy = self._healthy()
        if healthy:
            acknowledged = False
            try:
                client = httpx.Client(timeout=5)
                try:
                    response = client.post(f"{self._base_url}/shutdown")
                    # audio.cpp has no such endpoint (404). Waiting for silence
                    # after a refusal just makes every `down` five seconds slow.
                    acknowledged = response.status_code < 400
                finally:
                    client.close()
            except httpx.HTTPError:
                pass
            if acknowledged:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if not self._healthy():
                        break
                    time.sleep(0.25)
                if not self._healthy():
                    self._pid_path.unlink(missing_ok=True)
                    result: dict[str, object] = {"status": "down", "via": "http"}
                    if pid is not None:
                        result["pid"] = pid
                    return result
        if pid is None:
            if healthy:
                raise EngineUnavailable(
                    "the server is running but its pid is unknown; stop it manually"
                )
            return {"status": "down"}
        if not token:
            if healthy:
                raise EngineUnavailable(
                    "the pid file has no identity token; stop it manually"
                )
            self._pid_path.unlink(missing_ok=True)
            return {"status": "down", "via": "garbage"}
        try:
            handle = open_process(pid)
        except ProcessGone:
            # The file outlived its process: garbage, not a target.
            self._pid_path.unlink(missing_ok=True)
            return {"status": "down", "pid": pid, "via": "garbage"}
        except PidfdUnavailable as exc:
            # No identity, no kill. The file stays so the operator can decide.
            raise EngineUnavailable(
                "cannot verify the recorded pid belongs to this server; stop it manually"
            ) from exc
        try:
            if not identity_matches(pid, token):
                # Opened first, then read: a pid recycled in between answers with
                # the impostor's environment and fails here, before any signal.
                self._pid_path.unlink(missing_ok=True)
                if healthy:
                    raise EngineUnavailable(
                        "a server is running but its pid file does not match it; "
                        "stop it manually"
                    )
                return {"status": "down", "via": "garbage"}
            try:
                handle.signal(signal.SIGTERM)
            except ProcessGone:
                pass
            if not handle.wait(15):
                try:
                    # Same handle: the escalation signals the process this pidfd
                    # pinned, never a pid that may have been recycled since.
                    handle.signal(signal.SIGKILL)
                except ProcessGone:
                    pass
                handle.wait(5)
        except PidfdUnavailable as exc:
            raise EngineUnavailable(
                "cannot verify the recorded pid belongs to this server; stop it manually"
            ) from exc
        finally:
            handle.close()
        self._pid_path.unlink(missing_ok=True)
        return {"status": "down", "pid": pid, "via": "signal"}

    # ── pid bookkeeping ─────────────────────────────────────────────────
    def _write_pid(self, pid: int, token: str) -> None:
        """Persist the pid and its boot token atomically.

        A reader (``down``, another CLI, the operator) must never see a
        half-written file: a truncated pid reads as "unknown" and turns a live
        server into one nobody can stop. ``tmp`` + ``os.replace`` is an atomic
        rename on the same filesystem, the same trick ``active-job.json`` uses.
        """
        self._pid_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": pid,
            "port": self._port,
            "token": token,
            "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        tmp = self._pid_path.with_name(self._pid_path.name + ".tmp")
        tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        os.replace(tmp, self._pid_path)

    def _read_pid(self) -> tuple[int | None, str | None]:
        try:
            data = json.loads(self._pid_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None, None
        if not isinstance(data, dict):
            return None, None
        pid = data.get("pid")
        token = data.get("token")
        return (
            pid if isinstance(pid, int) else None,
            token if isinstance(token, str) else None,
        )

    def _healthy(self) -> bool:
        try:
            client = httpx.Client(timeout=2)
            try:
                return client.get(f"{self._base_url}/health").status_code == 200
            finally:
                client.close()
        except httpx.HTTPError:
            return False


def _wav_rate(audio: bytes) -> int:
    try:
        with wave.open(io.BytesIO(audio), "rb") as handle:
            return int(handle.getframerate())
    except Exception:  # noqa: BLE001
        return 44_100


def _wav_duration(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())
