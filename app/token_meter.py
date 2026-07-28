from __future__ import annotations
import time
from collections import deque


class TokenMeter:
    """Sliding-window token meter shared across all simulations.

    Records input/output token events with a monotonic timestamp and reports the
    sum over the last `window_s` seconds. With a 60s window the sums are, by
    definition, tokens-per-minute (TPM) — the same shape as the Gemini quota that
    the agent hits (input tokens per minute, including cached tokens).
    """

    def __init__(self, window_s: float = 60.0) -> None:
        self._window = window_s
        self._events: deque[tuple[float, int, int]] = deque()  # (ts, in, out)

    def record(self, in_tokens: int, out_tokens: int) -> None:
        now = time.monotonic()
        self._events.append((now, in_tokens, out_tokens))
        self._prune(now)

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def stats(self) -> dict:
        now = time.monotonic()
        self._prune(now)
        in_sum = sum(e[1] for e in self._events)
        out_sum = sum(e[2] for e in self._events)
        return {
            "input_tpm": in_sum,
            "output_tpm": out_sum,
            "total_tpm": in_sum + out_sum,
            "window_s": self._window,
            "samples": len(self._events),
        }


token_meter = TokenMeter()
