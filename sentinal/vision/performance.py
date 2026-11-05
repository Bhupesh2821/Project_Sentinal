"""Bounded timing statistics; no fabricated frame rates."""
from collections import deque
import math


class PerformanceMeter:
    def __init__(self, window=60):
        if window < 1:
            raise ValueError("Timing window must be positive")
        self._steps = deque(maxlen=window)
        self._inferences = deque(maxlen=window)

    def reset(self):
        self._steps.clear()
        self._inferences.clear()

    def record(self, elapsed_s, inference_ms):
        if not all(math.isfinite(v) and v >= 0 for v in (elapsed_s, inference_ms)):
            raise ValueError("Timings must be finite and nonnegative")
        self._steps.append(max(elapsed_s, 1e-9))
        self._inferences.append(inference_ms)

    @property
    def fps(self):
        return len(self._steps) / sum(self._steps) if self._steps else 0.0

    @property
    def average_inference_ms(self):
        return sum(self._inferences) / len(self._inferences) if self._inferences else 0.0
