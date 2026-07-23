from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Protocol


class PersistentMetrics(Protocol):
    def increment_metric(self, name: str, amount: int = 1) -> None: ...

    def metrics_snapshot(self) -> dict[str, int]: ...


class MetricsRegistry:
    def __init__(self, store: PersistentMetrics | None = None) -> None:
        self._values: Counter[str] = Counter()
        self._lock = Lock()
        self._store = store
        self.persistent = store is not None

    def increment(self, name: str, amount: int = 1) -> None:
        if self._store is not None:
            self._store.increment_metric(name, amount)
            return
        with self._lock:
            self._values[name] += amount

    def snapshot(self) -> dict[str, int]:
        if self._store is not None:
            return self._store.metrics_snapshot()
        with self._lock:
            return dict(sorted(self._values.items()))

    def prometheus(self) -> str:
        return "".join(
            f"# TYPE simuloom_{name} counter\nsimuloom_{name} {value}\n"
            for name, value in self.snapshot().items()
        )
