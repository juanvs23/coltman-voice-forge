#!/usr/bin/env python3
"""Model host for voice-forge.

Runs *inside the model virtualenv* (needs torch). Deliberately stdlib-only on
the HTTP side: no FastAPI, no Gradio, no dependency on anything the model
package happens to pull in. If this venv is rebuilt tomorrow, the host still
runs.

Contract (all JSON):

    GET  /health      -> {"status","models","device","emotion"}
    POST /warm        -> {"loaded":[...]}
    POST /design      -> {"candidates":[{"index","audio_b64","sample_rate","recipe"}]}
    POST /synthesize  -> {"duration": 1.23}
    POST /shutdown    -> {"status":"stopping"}

Swap this file for another host (IndexTTS, ZONOS3) and voice-forge does not
change a single line.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("HF_HOME", "/path/to/huggingface-cache")

DESIGN_REPO = os.getenv("VF_DESIGN_REPO", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
SPEECH_REPO = os.getenv("VF_SPEECH_REPO", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")

PREVIEW = {
    "Spanish": "La casa llevaba veinte años vacía, y aun así alguien cerró la puerta.",
    "English": "The house had been empty for twenty years, and yet someone closed the door.",
}

# How each domain axis is expressed to the model. The adapter owns this table;
# the domain only knows the eight names.
AXIS_WORDS = {
    "happy": "happy and bright",
    "angry": "angry and hard",
    "sad": "sad and heavy",
    "afraid": "frightened and tense",
    "disgusted": "disgusted",
    "melancholic": "melancholic and weary",
    "surprised": "surprised",
    "calm": "calm and measured",
}


def build_instruct(emotion: dict) -> str | None:
    """Turn domain emotion (axes + intensity + hint) into a model instruction."""
    axes = emotion.get("axes") or {}
    intensity = float(emotion.get("intensity", 0.6))
    hint = emotion.get("hint")
    if not axes and not hint:
        return None

    strength = "subtly" if intensity < 0.4 else "clearly" if intensity < 0.75 else "intensely"
    parts = [f"{strength} {AXIS_WORDS[axis]} ({value:.2f})" for axis, value in axes.items() if axis in AXIS_WORDS]
    text = "Voice performing " + ", with ".join(parts) if parts else ""
    if hint:
        text = (text + ". " + hint).strip(". ")
    return text.strip() or None


class Host:
    def __init__(self) -> None:
        self._design = None
        self._speech = None
        self._prompts: dict[tuple, object] = {}
        self._lock = threading.Lock()

    # ── model loading (one at a time: 8 GB card) ────────────────────────
    def _unload(self, which: str) -> None:
        import gc

        import torch

        if which == "design" and self._design is not None:
            self._design = None
        if which == "speech" and self._speech is not None:
            self._speech = None
            self._prompts.clear()
        gc.collect()
        torch.cuda.empty_cache()

    def _load(self, which: str):
        import torch
        from qwen_tts import Qwen3TTSModel

        if which == "design":
            if self._design is None:
                self._unload("speech")
                self._design = Qwen3TTSModel.from_pretrained(
                    DESIGN_REPO, device_map="cuda:0", dtype=torch.bfloat16,
                    attn_implementation="sdpa",
                )
            return self._design
        if self._speech is None:
            self._unload("design")
            self._speech = Qwen3TTSModel.from_pretrained(
                SPEECH_REPO, device_map="cuda:0", dtype=torch.bfloat16,
                attn_implementation="sdpa",
            )
        return self._speech

    # ── operations ──────────────────────────────────────────────────────
    def design(self, payload: dict) -> dict:
        import soundfile as sf

        description = payload["description"]
        language = payload.get("language", "Spanish")
        count = int(payload.get("candidates", 1))
        seed = payload.get("seed")
        preview = payload.get("preview_text") or PREVIEW.get(language, PREVIEW["English"])

        with self._lock:
            model = self._load("design")
            candidates = []
            for index in range(count):
                wavs, sr = model.generate_voice_design(
                    text=preview,
                    instruct=description,
                    language=language,
                )
                buffer = Path(tempfile.mkdtemp()) / "candidate.wav"
                sf.write(buffer, wavs[0], sr)
                candidates.append(
                    {
                        "index": index,
                        "audio_b64": base64.b64encode(buffer.read_bytes()).decode("ascii"),
                        "sample_rate": int(sr),
                        "recipe": {
                            "model": DESIGN_REPO,
                            "instruct": description,
                            "preview_text": preview,
                            "language": language,
                            "seed": seed,
                        },
                    }
                )
        return {"candidates": candidates}

    def synthesize(self, payload: dict) -> dict:
        import soundfile as sf

        text = payload["text"]
        ref_audio = payload["ref_audio"]
        ref_text = payload.get("ref_transcript")
        language = payload.get("language", "Spanish")
        out_path = Path(payload["out_path"])
        speed = float(payload.get("speed", 1.0))

        with self._lock:
            model = self._load("speech")
            key = (ref_audio, os.path.getmtime(ref_audio), bool(ref_text))
            prompt = self._prompts.get(key)
            if prompt is None:
                prompt = model.create_voice_clone_prompt(
                    ref_audio=ref_audio,
                    ref_text=ref_text,
                    x_vector_only_mode=ref_text is None,
                )
                self._prompts[key] = prompt

            wavs, sr = model.generate_voice_clone(
                text=text,
                language=language,
                voice_clone_prompt=prompt,
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(out_path, wavs[0], sr)

        if abs(speed - 1.0) > 1e-3:
            _retime(out_path, speed)

        info = sf.info(str(out_path))
        return {"duration": float(info.duration), "sample_rate": int(info.samplerate)}

    def warm(self, modes: list[str]) -> dict:
        loaded = []
        with self._lock:
            if "design" in modes:
                self._load("design")
                loaded.append("design")
            if "speech" in modes:
                self._load("speech")
                loaded.append("speech")
        return {"loaded": loaded}

    def status(self) -> dict:
        try:
            import torch

            device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001
            device = "unknown"
        return {
            "status": "up",
            "models": {"design": self._design is not None, "speech": self._speech is not None},
            "device": device,
            # Qwen3 Base clones but does not accept style instructions.
            "emotion": "unsupported-by-speech-backend",
        }


def _retime(path: Path, speed: float) -> None:
    """Apply tempo without changing pitch, using the system ffmpeg."""
    tmp = path.with_suffix(".retimed.wav")
    subprocess.run(  # noqa: S603
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-filter:a", f"atempo={max(0.5, min(2.0, speed))}", str(tmp)],
        check=False,
    )
    if tmp.exists():
        tmp.replace(path)


HOST = Host()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:  # keep the log readable
        pass

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(200, HOST.status())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return

        try:
            if self.path == "/warm":
                self._send(200, HOST.warm(payload.get("modes") or ["design", "speech"]))
            elif self.path == "/design":
                self._send(200, HOST.design(payload))
            elif self.path == "/synthesize":
                self._send(200, HOST.synthesize(payload))
            elif self.path == "/shutdown":
                self._send(200, {"status": "stopping"})
                threading.Thread(target=lambda: (time.sleep(0.2), os._exit(0)), daemon=True).start()
            else:
                self._send(404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - the client needs the reason
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8710)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    print(f"voice-forge model host on http://{args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
