"""HTTP client for the voice-forge API.

The MCP server is a *primary adapter* and a client of the running API, not a
second engine. Every call goes over HTTP to ``voice-forge serve`` so model work
still enters the single ``SerialQueue`` of that process: FIFO between agents,
and the admission lock stays the one truth.

There is one error funnel, ``_request``:

* a refused or timed-out connection becomes ``ApiUnavailable`` and says how to
  start the API;
* any response with status >= 400 becomes ``ApiError`` carrying the ``error``
  and ``hint`` fields the API already produces.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

DEFAULT_API_URL = "http://127.0.0.1:8720"

# Timeouts are per operation: a list is instant, a render is not.
FAST = 15.0
PREVIEW = 900.0
RENDER = 3600.0
DESIGN = 1800.0
REGISTER = 120.0
CLONE = 120.0
DERIVE = 300.0


class ApiUnavailable(RuntimeError):
    """``voice-forge serve`` is not reachable on the configured URL."""


class ApiError(RuntimeError):
    """The API answered, but with an error status."""

    def __init__(
        self,
        status: int | None,
        error: str,
        hint: str | None = None,
        raw: str | None = None,
    ) -> None:
        self.status = status
        self.error = error
        self.hint = hint
        self.raw = raw
        message = error
        if hint:
            message = f"{error} (hint: {hint})"
        super().__init__(message)


def _json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


class VoiceForgeClient:
    """Thin, typed wrapper over the voice-forge REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = FAST,
    ) -> None:
        url = base_url or os.environ.get("VOICEFORGE_API_URL") or DEFAULT_API_URL
        self.base_url = url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
        )

    # ── lifecycle ────────────────────────────────────────────────────────
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> VoiceForgeClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ── the single error funnel ──────────────────────────────────────────
    def _request(self, method: str, path: str, *, timeout: float, **kwargs) -> Any:
        try:
            response = self._client.request(method, path, timeout=timeout, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ApiUnavailable(
                f"voice-forge serve is not running on {self.base_url}; "
                "start it with `voice-forge serve`"
            ) from exc
        except httpx.HTTPError as exc:
            # Read timeouts and protocol errors are still API failures; surface
            # them through the same type so a tool has one error to handle.
            raise ApiError(None, f"{type(exc).__name__}: {exc}", raw=str(exc)) from exc

        if response.status_code >= 400:
            payload = _json_body(response)
            if isinstance(payload, dict):
                error = payload.get("error") or payload.get("detail") or response.text
                hint = payload.get("hint")
            else:
                error = response.text or response.reason_phrase
                hint = None
            raise ApiError(response.status_code, str(error), hint, raw=response.text)

        payload = _json_body(response)
        return payload if payload is not None else response.text

    # ── catalog ──────────────────────────────────────────────────────────
    def list_voices(self) -> list[dict]:
        return self._request("GET", "/api/voices", timeout=FAST)

    def show_voice(self, slug: str) -> dict:
        return self._request("GET", f"/api/voices/{slug}", timeout=FAST)

    def previews(self) -> list[dict]:
        return self._request("GET", "/api/previews", timeout=FAST)

    def preview_voice(
        self,
        slug: str,
        text: str,
        axes: dict[str, float] | None = None,
        intensity: float = 0.6,
        speed: float = 1.0,
        hint: str | None = None,
    ) -> dict:
        payload = {
            "text": text,
            "axes": dict(axes or {}),
            "intensity": intensity,
            "speed": speed,
            "hint": hint,
        }
        return self._request(
            "POST", f"/api/voices/{slug}/preview", timeout=PREVIEW, json=payload
        )

    def render_dialogue(
        self, script: str, out: str | None = None, master: bool = True
    ) -> dict:
        payload = {"script": script, "out": out, "master": master}
        return self._request(
            "POST", "/api/dialogues/render", timeout=RENDER, json=payload
        )

    # ── design flow ──────────────────────────────────────────────────────
    def design_candidates(
        self,
        description: str,
        candidates: int = 4,
        language: str = "Spanish",
        seed: int | None = None,
        preview_text: str | None = None,
        emotional: bool = False,
    ) -> dict:
        payload = {
            "description": description,
            "candidates": candidates,
            "language": language,
            "seed": seed,
            "preview_text": preview_text,
            "emotional": emotional,
        }
        return self._request(
            "POST", "/api/voices/design/candidates", timeout=DESIGN, json=payload
        )

    def register_candidate(
        self,
        token: str,
        pick: int,
        slug: str,
        name: str | None = None,
        tags: list[str] | None = None,
        emotional: bool = False,
    ) -> dict:
        payload = {
            "token": token,
            "pick": pick,
            "slug": slug,
            "name": name,
            "tags": list(tags or []),
            "emotional": emotional,
        }
        return self._request(
            "POST", "/api/voices/design/register", timeout=REGISTER, json=payload
        )

    def clone_voice(
        self,
        audio_path: str,
        slug: str,
        name: str | None = None,
        language: str = "Spanish",
        transcript: str | None = None,
        emotional: bool = False,
    ) -> dict:
        path = Path(audio_path)
        data = {
            "slug": slug,
            "language": language,
            "emotional": "true" if emotional else "false",
        }
        if name is not None:
            data["name"] = name
        if transcript is not None:
            data["transcript"] = transcript
        with path.open("rb") as handle:
            files = {"file": (path.name, handle, "application/octet-stream")}
            return self._request(
                "POST", "/api/voices", timeout=CLONE, data=data, files=files
            )

    def derive_voice(
        self,
        slug: str,
        new_slug: str,
        name: str | None = None,
        pitch: float | None = -2.0,
        timbre: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "slug": new_slug,
            "name": name,
            "tags": list(tags or []),
        }
        if timbre:
            # The API defaults the pitch when neither field arrives; sending
            # both would be rejected, so a timbre request carries no pitch.
            payload["timbre"] = timbre
        else:
            payload["pitch"] = pitch
        return self._request(
            "POST", f"/api/voices/{slug}/derive", timeout=DERIVE, json=payload
        )

    # ── diagnostics ──────────────────────────────────────────────────────
    def engine_status(self) -> dict:
        return self._request("GET", "/api/engine", timeout=FAST)

    def engine_action(self, action: str) -> dict:
        return self._request("POST", f"/api/engine/{action}", timeout=FAST)

    def queue_status(self) -> dict:
        return self._request("GET", "/api/queue", timeout=FAST)
