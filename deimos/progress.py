"""Live progress for the current turn.

A tiny thread-safe singleton the worker thread (brain/tools) writes to and the
server's event loop reads from, so the UI can show an honest phase label + how
long it's been running. This is elapsed time, not a fake countdown; an optional
estimate (from past build durations) is advisory only.
"""
import threading
import time


class Progress:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._phase = "Thinking"
        self._start: float | None = None
        self._estimate: int | None = None

    def start(self) -> None:
        with self._lock:
            self._start = time.monotonic()
            self._phase = "Thinking"
            self._estimate = None

    def stop(self) -> None:
        with self._lock:
            self._start = None
            self._phase = "Thinking"
            self._estimate = None

    def set_phase(self, name: str) -> None:
        with self._lock:
            self._phase = name or "Thinking"

    def set_estimate(self, seconds: int | None) -> None:
        with self._lock:
            self._estimate = int(seconds) if seconds else None

    def snapshot(self) -> tuple[str, int]:
        """Return (phase, elapsed_seconds)."""
        with self._lock:
            elapsed = int(time.monotonic() - self._start) if self._start else 0
            return self._phase, elapsed

    @property
    def estimate(self) -> int | None:
        with self._lock:
            return self._estimate


progress = Progress()
