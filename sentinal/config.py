"""Validated settings. Disk configuration never enables metadata recording."""
from dataclasses import dataclass, fields
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _finite_number(value):
    # Python integers are finite; converting very large ones through
    # math.isfinite can itself overflow. JSON booleans are not numbers here.
    return type(value) is int or (type(value) is float and math.isfinite(value))


@dataclass(frozen=True)
class AppConfig:
    model_path: str = "models/yolo11n.pt"
    confidence: float = 0.25
    image_size: int = 640
    device: str = "auto"
    camera_width: int = 640
    camera_height: int = 480
    sample_interval_s: float = 2.0
    retention_days: int = 7
    max_detection_rows: int = 100000
    stream_open_timeout_ms: int = 5000
    stream_read_timeout_ms: int = 2000
    stream_reconnect_attempts: int = 3
    stream_reconnect_delay_s: float = 1.0

    def __post_init__(self):
        if not _finite_number(self.confidence) or not 0.05 <= self.confidence <= 0.95:
            raise ValueError("Confidence must be between 0.05 and 0.95")
        if type(self.image_size) is not int or self.image_size not in (320, 480, 640, 960):
            raise ValueError("Image size must be 320, 480, 640 or 960")
        if not isinstance(self.device, str) or self.device not in ("auto", "cpu", "mps"):
            raise ValueError("Device must be auto, cpu or mps")
        if any(type(v) is not int or v < 64 for v in (self.camera_width, self.camera_height)):
            raise ValueError("Capture dimensions must be at least 64 pixels")
        if not _finite_number(self.sample_interval_s) or self.sample_interval_s < 0.5:
            raise ValueError("Metadata sampling interval must be at least 0.5 seconds")
        if type(self.retention_days) is not int or not 1 <= self.retention_days <= 365:
            raise ValueError("Metadata retention must be a whole number of days from 1 to 365")
        if type(self.max_detection_rows) is not int or not 100 <= self.max_detection_rows <= 1000000:
            raise ValueError("Metadata row limit must be 100 to 1000000")
        if not isinstance(self.model_path, str) or not self.model_path or Path(self.model_path).suffix != ".pt":
            raise ValueError("Model path must point to local .pt weights")
        if any(type(v) is not int or not 250 <= v <= 30000 for v in
               (self.stream_open_timeout_ms, self.stream_read_timeout_ms)):
            raise ValueError("Stream timeouts must be whole milliseconds from 250 to 30000")
        if type(self.stream_reconnect_attempts) is not int or not 0 <= self.stream_reconnect_attempts <= 5:
            raise ValueError("Stream reconnect attempts must be from zero to five")
        if not _finite_number(self.stream_reconnect_delay_s) or not 0.1 <= self.stream_reconnect_delay_s <= 10:
            raise ValueError("Stream reconnect delay must be from 0.1 to 10 seconds")

    @property
    def weights(self):
        p = Path(self.model_path).expanduser()
        return p if p.is_absolute() else ROOT / p


def load_config(path=None):
    p = Path(path) if path else ROOT / "config/settings.json"
    if not p.exists():
        return AppConfig()
    values = json.loads(p.read_text())
    if not isinstance(values, dict):
        raise ValueError("Settings must be a JSON object")
    unknown = set(values) - {f.name for f in fields(AppConfig)}
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
    return AppConfig(**values)
