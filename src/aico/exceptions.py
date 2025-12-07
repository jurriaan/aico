class AicoError(Exception):
    """Base exception for all expected aico errors."""

    message: str
    exit_code: int

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class ConfigurationError(AicoError):
    """Configuration related errors (env vars, config files)."""


class SessionError(AicoError):
    """General session errors."""


class SessionIntegrityError(AicoError):
    """Session corruption or invalid formats."""


class InvalidInputError(AicoError):
    """User input validation errors."""


class TrustError(AicoError):
    """Security/Trust related errors."""


class AddonExecutionError(AicoError):
    """Errors during addon execution."""


class ProviderError(AicoError):
    """LLM provider errors."""


class ExternalDependencyError(AicoError):
    """Missing system tools (git, editor)."""
