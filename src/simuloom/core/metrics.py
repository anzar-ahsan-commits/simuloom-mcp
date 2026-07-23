from __future__ import annotations

from collections import Counter
from threading import Lock


class MetricsRegistry:
    def __init__(self) -> None:
        self._values: Counter[str] = Counter()
        self._lock = Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._values[name] += amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._values.items()))

    def prometheus(self) -> str:
        return "".join(
            f"# TYPE simuloom_{name} counter\nsimuloom_{name} {value}\n"
            for name, value in self.snapshot().items()
        )
