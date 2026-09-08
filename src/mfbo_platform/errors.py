class PlatformError(Exception):
    """Base exception safe to translate at the application boundary."""


class NotFoundError(PlatformError):
    pass


class ConflictError(PlatformError):
    pass


class CancelledError(PlatformError):
    pass


class WorkerShutdownError(PlatformError):
    pass


class LeaseLostError(PlatformError):
    pass


class EngineError(PlatformError):
    def __init__(self, message: str, *, retryable: bool = False, code: str = "engine_error"):
        super().__init__(message)
        self.retryable = retryable
        self.code = code
