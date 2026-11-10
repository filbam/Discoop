"""Exit codes and the error type that commands raise."""

from enum import IntEnum


class ExitCode(IntEnum):
    """Stable exit codes (docs/design.md, section 12)."""

    OK = 0
    ERROR = 1
    AUTH_REQUIRED = 2
    AMBIGUOUS = 3
    NOT_FOUND = 4
    NO_ACCESS = 5
    RATE_LIMITED = 6
    NETWORK = 7
    BAD_ARGS = 8
    PARTIAL = 9  # finished, but a channel was skipped (no access, not found) or a file could not be downloaded


AUTH_HINT = (
    "Run `discoop login` (or `discoop login --browser`). AI agents: tell the user a browser window will open in "
    "which they log in themselves, wait for their consent, then run `discoop login --browser`; never run "
    "`discoop login` or `login --token` yourself."
)


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
