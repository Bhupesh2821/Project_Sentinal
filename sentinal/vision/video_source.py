"""Exclusive camera capture and finite local-video decoding, independent of Qt."""
from dataclasses import dataclass, field
import logging
import math
from pathlib import Path
import sys
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

import cv2

log = logging.getLogger(__name__)
_camera_guard = Lock()
_active_cameras = set()


class VideoSourceError(RuntimeError):
    pass


def _claim_camera(index):
    with _camera_guard:
        if index in _active_cameras:
            raise VideoSourceError("That camera is already open in SENTINAL. Stop the current session first.")
        _active_cameras.add(index)


def _release_camera(index):
    with _camera_guard:
        _active_cameras.discard(index)


def _stream_parts(value):
    message = "Enter a valid RTSP, RTSPS, HTTP or HTTPS camera address."
    if not isinstance(value, str) or not value or len(value) > 8192 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(message)
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"rtsp", "rtsps", "http", "https"} or not parts.hostname:
            raise ValueError(message)
        if parts.fragment or chr(92) in parts.hostname or (parts.port is not None and not 1 <= parts.port <= 65535):
            raise ValueError(message)
        parts.hostname.encode("idna")
        return parts
    except (ValueError, UnicodeError):
        raise ValueError(message) from None


@dataclass(frozen=True, repr=False)
class SourceSpec:
    kind: str
    value: int | str = field(repr=False)
    camera_device_id: str = field(default="", repr=False)
    camera_name: str = ""

    def __post_init__(self):
        if not isinstance(self.kind, str) or self.kind not in {"camera", "file", "stream"}:
            raise ValueError("Source must be camera, file or stream")
        if self.kind == "camera" and (type(self.value) is not int or self.value < 0):
            raise ValueError("Camera source requires a nonnegative integer index")
        if self.kind == "file" and (not isinstance(self.value, str) or not self.value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in self.value)):
            raise ValueError("File source requires a local path")
        if not isinstance(self.camera_device_id, str) or len(self.camera_device_id) > 2048:
            raise ValueError("Camera device identity must be a hexadecimal string")
        if self.camera_device_id:
            try:
                if len(self.camera_device_id) % 2 or any(c not in "0123456789abcdefABCDEF" for c in self.camera_device_id):
                    raise ValueError()
                bytes.fromhex(self.camera_device_id)
            except ValueError:
                raise ValueError("Camera device identity must be a hexadecimal string") from None
            object.__setattr__(self, "camera_device_id", self.camera_device_id.lower())
        if not isinstance(self.camera_name, str) or len(self.camera_name) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in self.camera_name):
            raise ValueError("Camera name must be a short display label")
        if self.kind != "camera" and (self.camera_device_id or self.camera_name):
            raise ValueError("Camera identity is only valid for camera sources")
        if self.kind == "stream":
            _stream_parts(self.value)

    @property
    def camera_key(self):
        return self.camera_device_id or self.value

    @property
    def description(self):
        return source_description(self)

    def __repr__(self):
        return f"SourceSpec(kind={self.kind!r}, description={self.description!r})"


def source_description(spec):
    if spec.kind == "camera":
        return spec.camera_name or f"Camera {spec.value}"
    if spec.kind == "file":
        return Path(spec.value).name
    parts = _stream_parts(spec.value)
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    if parts.port is not None:
        host += f":{parts.port}"
    return f"{parts.scheme.upper()} camera · {host}"


class VideoSource:
    def __init__(self, spec, width=640, height=480, open_timeout_ms=5000, read_timeout_ms=2000):
        self.spec = spec
        self.width, self.height = width, height
        if any(type(v) is not int or not 1 <= v <= 120000 for v in (open_timeout_ms, read_timeout_ms)):
            raise ValueError("Capture timeouts must be positive whole milliseconds up to 120000")
        self.open_timeout_ms, self.read_timeout_ms = open_timeout_ms, read_timeout_ms
        self.state = "closed"
        self.capture = None
        self.fps = 0.0
        self.source_time_s = 0.0
        self.frame_index = 0
        self.frame_count = 0
        self._owns_camera = False
        self._started_at = 0.0

    @property
    def description(self):
        return self.spec.description

    @property
    def duration_s(self):
        return self.frame_count / self.fps if self.spec.kind == "file" and self.fps > 0 and self.frame_count > 0 else None

    def open(self):
        if self.state == "open":
            return self
        self.close()
        self.frame_index, self.source_time_s = 0, 0.0
        try:
            if self.spec.kind == "file":
                path = Path(self.spec.value).expanduser()
                if not path.is_file():
                    raise VideoSourceError("The selected video file no longer exists.")
                self.capture = cv2.VideoCapture(str(path))
            elif self.spec.kind == "stream":
                self.capture = cv2.VideoCapture(self.spec.value, cv2.CAP_FFMPEG, [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.open_timeout_ms,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.read_timeout_ms])
            else:
                _claim_camera(self.spec.camera_key)
                self._owns_camera = True
                if self.spec.camera_device_id:
                    from .qt_camera import QtCameraCapture
                    self.capture = QtCameraCapture(self.spec.camera_device_id, self.width, self.height,
                                                   self.open_timeout_ms, self.read_timeout_ms)
                elif sys.platform == "darwin":
                    raise VideoSourceError("Choose a named camera from the refreshed camera list before starting. SENTINAL will not open a macOS default camera automatically.")
                else:
                    self.capture = cv2.VideoCapture(self.spec.value, cv2.CAP_ANY)
            if not self.capture.isOpened():
                if self.spec.kind == "camera":
                    raise VideoSourceError("Camera unavailable. Connect a camera and allow camera access for the launcher in System Settings → Privacy & Security → Camera.")
                if self.spec.kind == "stream":
                    raise VideoSourceError("Network camera could not be opened. Check its address, credentials, connection and stream format.")
                raise VideoSourceError("This video could not be opened. It may be corrupt or use an unsupported codec.")
            if self.spec.kind == "camera":
                self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # best effort; AVFoundation may ignore
            elif self.spec.kind == "file" and hasattr(cv2, "CAP_PROP_ORIENTATION_AUTO"):
                self.capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
            fps = float(self.capture.get(cv2.CAP_PROP_FPS))
            count = float(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
            self.fps = fps if math.isfinite(fps) and fps > 0 else 0.0
            self.frame_count = int(count) if self.spec.kind == "file" and math.isfinite(count) and count > 0 else 0
            self._started_at = monotonic()
            self.state = "open"
            return self
        except Exception as exc:
            self.close()
            self.state = "error"
            if isinstance(exc, VideoSourceError):
                raise
            if self.spec.kind == "stream":
                raise VideoSourceError("Network camera could not be opened. Check its address, credentials, connection and stream format.") from None
            if self.spec.kind == "camera":
                from .qt_camera import CameraCaptureError
                if isinstance(exc, CameraCaptureError):
                    raise VideoSourceError(str(exc)) from None
            log.exception("Failed to open video source")
            raise VideoSourceError("The video source could not be opened. See the diagnostic log.") from exc

    def read(self):
        if self.state == "eof":
            return None
        if self.state != "open" or self.capture is None:
            raise VideoSourceError("No video source is open. Start monitoring first.")
        try:
            ok, frame = self.capture.read()
            if not ok or frame is None or not frame.size:
                if self.spec.kind == "camera":
                    raise VideoSourceError("The camera stopped delivering frames. Check its connection and camera permission, then start again.")
                if self.spec.kind == "stream":
                    raise VideoSourceError("Network camera stopped delivering frames. Check its connection, then reconnect.")
                if self.frame_index == 0:
                    raise VideoSourceError("No frames could be decoded. The video may be empty, corrupt or use an unsupported codec.")
                if self.frame_count and self.frame_index < self.frame_count - 1:
                    raise VideoSourceError("The video ended before its advertised final frame. It may be damaged.")
                self.close()
                self.state = "eof"
                return None
            self.frame_index += 1
            if self.spec.kind in {"camera", "stream"}:
                self.source_time_s = monotonic() - self._started_at
            else:
                millis = float(self.capture.get(cv2.CAP_PROP_POS_MSEC))
                self.source_time_s = millis / 1000 if math.isfinite(millis) and millis >= 0 else 0.0
                if not self.source_time_s and self.fps:
                    self.source_time_s = (self.frame_index - 1) / self.fps
            return frame
        except Exception as exc:
            self.close()
            self.state = "error"
            if isinstance(exc, VideoSourceError):
                raise
            if self.spec.kind == "stream":
                raise VideoSourceError("Network camera stopped unexpectedly. Check its connection, then reconnect.") from None
            if self.spec.kind == "camera":
                from .qt_camera import CameraCaptureError
                if isinstance(exc, CameraCaptureError):
                    raise VideoSourceError(str(exc)) from None
            log.exception("Video capture failed")
            raise VideoSourceError("The video source stopped unexpectedly. See the diagnostic log.") from exc

    def seek(self, seconds):
        if self.spec.kind != "file" or self.state != "open" or self.capture is None:
            raise VideoSourceError("Seeking is available only while a local video is open.")
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Video position must be a finite, nonnegative number of seconds")
        if self.duration_s is not None:
            seconds = min(float(seconds), self.duration_s)
        target = int(float(seconds) * self.fps) if self.fps else 0
        # Media-time seeking works with variable-rate recordings where average
        # FPS does not map a time to an exact frame. Some backends require the
        # frame-position fallback; those seeks remain decoder-dependent.
        accepted = self.capture.set(cv2.CAP_PROP_POS_MSEC, float(seconds) * 1000)
        if not accepted and self.fps:
            accepted = self.capture.set(cv2.CAP_PROP_POS_FRAMES, target)
        if not accepted:
            raise VideoSourceError("This video decoder does not support seeking.")
        actual = float(self.capture.get(cv2.CAP_PROP_POS_FRAMES))
        self.frame_index = int(actual) if math.isfinite(actual) and actual >= 0 else target
        self.source_time_s = self.frame_index / self.fps if self.fps else float(seconds)
        return self.source_time_s

    def close(self):
        try:
            if self.capture is not None:
                self.capture.release()
        except Exception:
            if self.spec.kind != "stream":
                log.exception("Capture backend reported an error while releasing resources")
        finally:
            self.capture = None
            if self._owns_camera:
                _release_camera(self.spec.camera_key)
                self._owns_camera = False
            self.state = "closed"

    def restart(self):
        self.close()
        return self.open()

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.close()
