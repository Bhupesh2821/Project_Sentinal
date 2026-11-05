"""Camera discovery through device metadata; never opens a capture session."""
from dataclasses import dataclass
import logging

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CameraInfo:
    index: int
    name: str
    device_id: str = ""
    is_default: bool = False

    @property
    def is_builtin(self):
        name = self.name.casefold()
        return not any(word in name for word in ("iphone", "ipad", "continuity")) and any(
            word in name for word in ("facetime", "built-in", "macbook"))

    @property
    def category(self):
        if self.is_builtin:
            return "Mac camera"
        if any(word in self.name.casefold() for word in ("iphone", "ipad", "continuity")):
            return "Phone camera"
        return "External camera"


def discover_cameras():
    """List macOS cameras without activating them.

    Indices are display hints only. Capture uses the exact stable device_id and
    never maps Qt metadata order to an OpenCV/default-camera index.
    """
    try:
        from PySide6.QtMultimedia import QMediaDevices
        default_id = bytes(QMediaDevices.defaultVideoInput().id())
        return [CameraInfo(i, camera.description(), bytes(camera.id()).hex(), bytes(camera.id()) == default_id)
                for i, camera in enumerate(QMediaDevices.videoInputs())]
    except Exception:
        log.exception("Passive camera enumeration failed")
        return []


class CameraManager:
    discover = staticmethod(discover_cameras)
