"""The API must keep answering while a render is in flight.

A render blocks its own request until the queue worker is done; the queue
endpoint must still answer. With every handler declared ``async`` and calling
the blocking ``queue.wait``, the event loop stalls and this test hangs: the
render never yields, so ``GET /api/queue`` never runs. Handlers that do
synchronous work are plain ``def`` now, so Starlette runs them in its
threadpool.
"""

from __future__ import annotations

import asyncio
import threading
import time

import httpx

from voiceforge.adapters.primary.http import create_app


class GatedSynthesizer:
    """Blocks the line until the test opens the gate."""

    def __init__(self, inner, gate: threading.Event, entered: threading.Event) -> None:
        self._inner = inner
        self._gate = gate
        self._entered = entered

    def synthesize(self, *, text, voice, emotion, speed, out_path):
        self._entered.set()
        if not self._gate.wait(10):
            raise AssertionError("the render never got past the gate")
        return self._inner.synthesize(
            text=text, voice=voice, emotion=emotion, speed=speed, out_path=out_path
        )


SCRIPT = (
    "title: demo\n"
    "lines:\n"
    "  - voice: voz\n"
    "    text: 'La casa estaba vacía.'\n"
)


def test_queue_answers_while_a_render_is_blocked(container):
    gate = threading.Event()
    entered = threading.Event()
    container.dialogue._synth = GatedSynthesizer(container.dialogue._synth, gate, entered)
    app = create_app(container)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            design = await client.post(
                "/api/voices/design",
                json={"description": "narrador grave", "slug": "voz", "candidates": 1},
            )
            assert design.status_code == 201

            render = asyncio.create_task(
                client.post("/api/dialogues/render", json={"script": SCRIPT})
            )

            for _ in range(500):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set(), "the render never reached the synthesizer"

            started = time.monotonic()
            queue = await client.get("/api/queue")
            elapsed = time.monotonic() - started

            assert elapsed < 1.0, f"the queue endpoint blocked for {elapsed:.2f}s"
            assert queue.status_code == 200
            body = queue.json()
            assert body["busy"] is True
            assert body["running"], "the blocked render must be the running job"

            gate.set()
            response = await render
            assert response.status_code == 200
            assert response.json()["lines"] == 1

    try:
        asyncio.run(scenario())
    finally:
        gate.set()
