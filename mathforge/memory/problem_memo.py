from __future__ import annotations

from typing import Callable, TypeVar


T = TypeVar("T")


class ProblemMemo:
    """Small solve-local memo; instances must never be shared across cases."""

    def __init__(self) -> None:
        self._values: dict[str, object] = {}

    def get_or_compute(self, key: str, compute: Callable[[], T]) -> T:
        if key not in self._values:
            self._values[key] = compute()
        return self._values[key]  # type: ignore[return-value]

    def clear(self) -> None:
        self._values.clear()

