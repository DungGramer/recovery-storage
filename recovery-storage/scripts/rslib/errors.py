"""Command outcome exceptions -> CLI exit codes (phase 01: 2 usage, 3 refused, 4 tool/env, 5 needs human)."""


class CommandError(Exception):
    exit_code = 1

    def __init__(self, message="", reasons=(), data=None):
        super().__init__(message)
        self.message = message
        self.reasons = list(reasons)
        self.data = data or {}


class UsageError(CommandError):
    exit_code = 2


class Refused(CommandError):
    exit_code = 3


class EnvFailure(CommandError):
    exit_code = 4


class NeedsHuman(CommandError):
    exit_code = 5
