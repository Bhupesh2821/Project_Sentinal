"""Exact-device Qt camera adapter, used only inside the live capture process.

Device enumeration is passive. Capture resolves the requested device ID afresh;
its disappearance is an error and never selects the system default camera.
"""
from time import monotonic, sleep

import cv2
import numpy as np


class CameraCaptureError(RuntimeError):
    """Safe camera errors suitable for display without native driver details."""


class QtCameraCapture:
    def __init__(self, device_id, width=640, height=480, open_timeout_ms=5000,
                 read_timeout_ms=2000):
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
        self._app = QCoreApplication.instance() or QCoreApplication([])
        self._camera = self._session = self._sink = None
        self._device_id = device_id
        self._latest = None
        self._error = None
        self._opened = False
        self._fps = 0.0
        self._shape = (height, width)
        self._read_timeout_s = read_timeout_ms / 1000
        self._device_check_at = 0.0
        devices = QMediaDevices.videoInputs()
        selected = next((d for d in devices if bytes(d.id()).hex() == device_id), None)
        if selected is None:
            raise CameraCaptureError("The selected camera is no longer available. Refresh the camera list and select it again. No other camera was opened.")
        try:
            self._camera = QCamera(selected)
            if bytes(self._camera.cameraDevice().id()).hex() != device_id:
                raise CameraCaptureError("The selected camera identity could not be opened. No alternative camera will be used.")
            self._session = QMediaCaptureSession()
            self._sink = QVideoSink()
            self._session.setCamera(self._camera)
            self._session.setVideoSink(self._sink)
            self._sink.videoFrameChanged.connect(self._on_frame)
            self._camera.errorOccurred.connect(self._on_error)
            formats = selected.videoFormats()
            if formats:
                preferred = min(formats, key=lambda f: (
                    abs(f.resolution().width() - width) + abs(f.resolution().height() - height),
                    abs(min(30.0, f.maxFrameRate()) - 30),
                ))
                self._camera.setCameraFormat(preferred)
                self._fps = float(preferred.maxFrameRate())
            self._camera.start()
            deadline = monotonic() + open_timeout_ms / 1000
            while monotonic() < deadline:
                self._app.processEvents()
                if self._error:
                    raise CameraCaptureError(self._error)
                if self._latest is not None:
                    self._opened = True
                    return
                sleep(.003)
            raise CameraCaptureError("The selected camera did not deliver a frame. Check its connection, unlock your iPhone if selected, and allow camera access in macOS Settings.")
        except Exception:
            self.release()
            raise

    def _on_error(self, *_):
        self._error = "The selected camera is unavailable. Check its connection and macOS camera permission, then select it and start again."

    def _on_frame(self, video_frame):
        if not video_frame.isValid():
            return
        from PySide6.QtGui import QImage
        image = video_frame.toImage()
        if image.isNull():
            return
        image = image.convertToFormat(QImage.Format.Format_BGR888)
        height, width = image.height(), image.width()
        # Copy before Qt returns/recycles its image storage. Respect row padding.
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8,
                               count=image.sizeInBytes()).reshape(height, image.bytesPerLine())
        self._latest = pixels[:, :width * 3].reshape(height, width, 3).copy()
        self._shape = (height, width)

    def isOpened(self):
        return self._opened and self._camera is not None and not self._error

    def read(self):
        from PySide6.QtMultimedia import QMediaDevices
        deadline = monotonic() + self._read_timeout_s
        while monotonic() < deadline:
            self._app.processEvents()
            if self._error:
                raise CameraCaptureError(self._error)
            if bytes(self._camera.cameraDevice().id()).hex() != self._device_id:
                raise CameraCaptureError("The active camera identity changed. Monitoring stopped; explicitly select a camera before restarting.")
            now = monotonic()
            if now >= self._device_check_at:
                self._device_check_at = now + .5
                if not any(bytes(d.id()).hex() == self._device_id for d in QMediaDevices.videoInputs()):
                    raise CameraCaptureError("The selected camera disconnected. Select it again after reconnecting; no other camera was opened.")
            if self._latest is not None:
                frame, self._latest = self._latest, None
                return True, frame
            sleep(.003)
        raise CameraCaptureError("The selected camera stopped delivering frames. Check its connection, then start again.")

    def get(self, prop):
        if prop == cv2.CAP_PROP_FPS:
            return self._fps
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return self._shape[1]
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return self._shape[0]
        return 0.0

    def set(self, *_):
        return False  # Format is selected once, before camera start.

    def release(self):
        self._opened = False
        if self._camera is not None:
            self._camera.stop()
        if self._session is not None:
            self._session.setVideoSink(None)
            self._session.setCamera(None)
        self._app.processEvents()
        for obj in (self._sink, self._session, self._camera):
            if obj is not None:
                obj.deleteLater()
        self._app.processEvents()
        self._sink = self._session = self._camera = None
        self._latest = None
