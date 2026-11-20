"""Domain errors. No infrastructure, no model names."""


class VoiceForgeError(Exception):
    """Base class for every error the system raises on purpose."""


class ValidationError(VoiceForgeError):
    """An input violates a domain rule."""


class VoiceNotFound(VoiceForgeError):
    """The requested slug is not in the catalog."""


class VoiceExists(VoiceForgeError):
    """The slug is already taken; voices are immutable once registered."""


class EngineUnavailable(VoiceForgeError):
    """The model host is not reachable or refused the request."""


class EngineAlreadyRunning(VoiceForgeError):
    """A second instance was requested while one is already alive."""


class EngineBusy(VoiceForgeError):
    """The host is working; stopping it now would discard a render."""


class RenderFailed(VoiceForgeError):
    """Audio assembly failed."""


class BuildFailed(VoiceForgeError):
    """The model runtime could not be selected, fetched or compiled."""
