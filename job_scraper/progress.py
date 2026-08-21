from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class Progress:
    def __init__(self, on_update: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._lock = threading.Lock()
        self.done = 0
        self.total = 0
        self.message = "Starting…"
        self._on_update = on_update

    def set_total(self, total: int, message: str | None = None) -> None:
        with self._lock:
            self.total = max(0, int(total))
            if message is not None:
                self.message = message
        self._emit()

    def set_message(self, message: str) -> None:
        with self._lock:
            self.message = message
        self._emit()

    def step(self, message: str | None = None) -> None:
        with self._lock:
            self.done += 1
            if message is not None:
                self.message = message
        self._emit()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = self.total
            done = self.done
            percent = 0
            if total > 0:
                percent = min(99, int(round(100 * done / total)))
            return {
                "done": done,
                "total": total,
                "percent": percent,
                "message": self.message,
            }

    def _emit(self) -> None:
        if self._on_update:
            self._on_update(self.snapshot())
