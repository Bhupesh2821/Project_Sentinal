"""UI-independent, immutable vision contracts. Coordinates are pixels of FramePacket.frame; live capture may resize before delivery."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any

BAG_CLASSES = frozenset({"backpack", "handbag", "suitcase"})
FOCUS_CLASSES = BAG_CLASSES | {"person"}


@dataclass(frozen=True)
class Detection:
    class_id: int
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]
    track_id: int | None = None

    def __post_init__(self):
        if self.class_id < 0 or not self.label:
            raise ValueError("Detection requires a class ID and label")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Confidence must be finite and between zero and one")
        if len(self.bbox) != 4 or not all(math.isfinite(v) for v in self.bbox):
            raise ValueError("Bounding box must contain four finite coordinates")
        x1, y1, x2, y2 = self.bbox
        if min(x1, y1) < 0 or x2 <= x1 or y2 <= y1:
            raise ValueError("Bounding box must have positive area and nonnegative coordinates")
        if self.track_id is not None and self.track_id < 0:
            raise ValueError("Track ID cannot be negative")


def count_objects(detections):
    return {
        "people": sum(d.label == "person" for d in detections),
        "bags": sum(d.label in BAG_CLASSES for d in detections),
        "tracked": sum(d.track_id is not None for d in detections),
        "detections": len(detections),
    }


@dataclass(frozen=True)
class FramePacket:
    frame: Any
    detections: tuple[Detection, ...]
    session_id: str
    source: str
    frame_index: int
    timestamp: str
    source_time_s: float
    fps: float
    inference_ms: float
    average_inference_ms: float
    device: str
    frame_age_ms: float = 0.0
    dropped_frames: int = 0
    model_name: str = ""
    hazards: tuple = ()
    hazard_sampled: bool = False
    detector_health: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
