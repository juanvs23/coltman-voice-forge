"""MCP primary adapter: stdio tools backed by the voice-forge HTTP API.

The server is a client of ``voice-forge serve``, never a second engine, so all
model work stays behind the API's single ``SerialQueue``.
"""

from .client import ApiError, ApiUnavailable, VoiceForgeClient
from .server import build_server, run_stdio

__all__ = [
    "ApiError",
    "ApiUnavailable",
    "VoiceForgeClient",
    "build_server",
    "run_stdio",
]
