"""Drive ``voice-forge mcp`` over real stdio and prove stdout is protocol-only.

Raw newline-delimited JSON-RPC on purpose: an SDK client would hide the very
thing this run checks, namely that the child writes nothing to stdout except
MCP messages. Every stdout line must parse as JSON; a banner, a ``print`` or a
stray log line fails the run.

Usage (with ``voice-forge serve`` already running):

    uv run python tests/e2e/mcp-stdio/handshake.py
"""

from __future__ import annotations

import json
import select
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent / "evidence"
EXPECTED_SLUGS = {
    "alex",
    "alex-grave",
    "narrador-energico",
    "narrador-terror",
    "narradora-ming",
}
MIN_TOOLS = 12


class Child:
    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            ["uv", "run", "voice-forge", "mcp"],
            cwd=REPO,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.stdout_lines: list[str] = []

    def send(self, message: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def read(self, timeout: float = 60.0) -> dict:
        assert self.proc.stdout is not None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no message from the MCP server in time")
            ready, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not ready:
                raise TimeoutError("no message from the MCP server in time")
            line = self.proc.stdout.readline()
            if line == "":
                raise RuntimeError("the MCP server closed stdout")
            stripped = line.rstrip("\n")
            if not stripped:
                continue
            self.stdout_lines.append(stripped)
            # This is the purity check: nothing but JSON may reach stdout.
            return json.loads(stripped)

    def wait_for(self, message_id: int, timeout: float = 60.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            message = self.read(timeout=max(0.1, deadline - time.monotonic()))
            if message.get("id") == message_id and "method" not in message:
                return message
            # Anything else (a server notification, a log record on the
            # protocol channel) is skipped here but stays in stdout_lines.

    def close(self) -> tuple[int, str]:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        stderr = self.proc.stderr.read() if self.proc.stderr else ""
        code = self.proc.wait(timeout=30)
        return code, stderr


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    child = Child()
    slugs: set[str] = set()
    summary: dict = {
        "protocol_version": "?",
        "server_name": "?",
        "tools": [],
        "tool_count": 0,
        "voices": [],
        "listed_count": -1,
    }
    try:
        child.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "voice-forge-e2e", "version": "0"},
                },
            }
        )
        init = child.wait_for(1)
        protocol = init["result"]["protocolVersion"]
        server_name = init["result"]["serverInfo"]["name"]

        child.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        child.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = child.wait_for(2)
        names = sorted(tool["name"] for tool in listed["result"]["tools"])

        child.send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_voices", "arguments": {}},
            }
        )
        called = child.wait_for(3)
        result = called["result"]
        assert not result.get("isError"), result
        payload = json.loads(result["content"][0]["text"])
        voices = payload["voices"]
        slugs = {voice["slug"] for voice in voices}

        # Safety guard, over the real protocol: a render must not be able to
        # overwrite a voice reference. The tool refuses before any job starts.
        child.send(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "render_dialogue",
                    "arguments": {
                        "script": "lines: []",
                        "out": "catalog/alex/ref.wav",
                    },
                },
            }
        )
        refused = child.wait_for(4)["result"]
        refusal_text = refused["content"][0]["text"]

        summary = {
            "protocol_version": protocol,
            "server_name": server_name,
            "tools": names,
            "tool_count": len(names),
            "voices": sorted(slugs),
            "listed_count": payload["count"],
            "refusal_is_error": bool(refused.get("isError")),
            "refusal_text": refusal_text,
        }
    finally:
        code, stderr = child.close()
        (EVIDENCE / "handshake.stdout.jsonl").write_text(
            "\n".join(child.stdout_lines) + "\n", encoding="utf-8"
        )
        (EVIDENCE / "handshake.stderr.log").write_text(stderr, encoding="utf-8")
        summary["stdout_lines"] = len(child.stdout_lines)
        summary["exit_code"] = code
        (EVIDENCE / "handshake.summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )

    print(f"protocol {summary['protocol_version']} · server {summary['server_name']}")
    print(f"tools ({summary['tool_count']}): {', '.join(summary['tools'])}")
    print(f"voices ({len(summary['voices'])}): {', '.join(summary['voices'])}")
    print(f"stdout lines all JSON: yes ({summary['stdout_lines']})")

    # The refused call must have left the catalog intact: `verify` still says ok.
    verified = subprocess.run(
        ["uv", "run", "voice-forge", "verify"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    (EVIDENCE / "verify-after-refusal.txt").write_text(verified.stdout, encoding="utf-8")
    alex_line = next(
        (line.strip() for line in verified.stdout.splitlines() if line.strip().startswith("alex ")),
        "",
    )
    print(f"verify after refusal: exit {verified.returncode} · {alex_line or 'no alex line'}")

    failures = []
    if summary["tool_count"] < MIN_TOOLS:
        failures.append(f"expected at least {MIN_TOOLS} tools, got {summary['tool_count']}")
    if not EXPECTED_SLUGS <= slugs:
        failures.append(f"missing voices: {sorted(EXPECTED_SLUGS - slugs)}")
    if any("remove_voice" in name or "delete" in name for name in summary["tools"]):
        failures.append("a destructive tool is exposed")
    if summary["listed_count"] != len(slugs):
        failures.append("count does not match the voices array")
    if not summary.get("refusal_is_error"):
        failures.append("render_dialogue accepted a path inside catalog/")
    if "catalog" not in summary.get("refusal_text", "").lower():
        failures.append("the refusal did not explain the catalog rule")
    if verified.returncode != 0:
        failures.append(f"voice-forge verify failed with exit {verified.returncode}")
    if not alex_line.endswith("ok"):
        failures.append(f"alex is not ok after the refused render: {alex_line!r}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
