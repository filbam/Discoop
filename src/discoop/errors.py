"""Exit codes and the error type that commands raise."""

from enum import IntEnum


class ExitCode(IntEnum):
    """Stable exit codes (docs/navrh-nastroja.md, section 12)."""

    OK = 0
    ERROR = 1
    AUTH_REQUIRED = 2
    AMBIGUOUS = 3
    NOT_FOUND = 4
    NO_ACCESS = 5
    RATE_LIMITED = 6
    NETWORK = 7
    BAD_ARGS = 8


AUTH_HINT = "Run `discoop login`. AI agents: ask the user to run it in their own terminal."


class DiscoopError(Exception):
    """An expected failure: printed as `ERROR <NAME>: message` plus an optional hint."""

    def __init__(self, code: ExitCode, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    @property
    def name(self) -> str:
        return self.code.name


def auth_required(message: str = "Not logged in.") -> DiscoopError:
    return DiscoopError(ExitCode.AUTH_REQUIRED, message, AUTH_HINT)
