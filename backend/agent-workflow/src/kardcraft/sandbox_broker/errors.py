"""Error model for sandbox broker."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrokerError:
    code: str
    message: str


class BrokerException(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_error(self) -> BrokerError:
        return BrokerError(code=self.code, message=self.message)
