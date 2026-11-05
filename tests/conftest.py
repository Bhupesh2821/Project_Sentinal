"""Test setup; synthetic records are unit-test inputs, never inference evidence."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentinal.vision.types import Detection, FramePacket, utc_now


@pytest.fixture
def packet():
    return FramePacket(
        frame=np.zeros((48, 64, 3), dtype=np.uint8),
        detections=(Detection(0, "person", 0.91, (1, 2, 25, 45), 7),
                    Detection(24, "backpack", 0.75, (30, 5, 50, 30), 9)),
        session_id="unit-session-a", source="unit-test.mp4", frame_index=1,
        timestamp=utc_now(), source_time_s=0.04,
        fps=24.5, inference_ms=25.0, average_inference_ms=26.0, device="cpu",
    )


@pytest.fixture
def synthetic_video(tmp_path):
    """Codec/state fixture only. This is explicitly not real-inference evidence."""
    import cv2
    path = tmp_path / "codec-state-fixture.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    if not writer.isOpened():
        pytest.skip("MJPG encoder is unavailable in this OpenCV build")
    try:
        for index in range(5):
            frame = np.zeros((48, 64, 3), dtype=np.uint8)
            frame[:, :, 1] = index * 40
            writer.write(frame)
    finally:
        writer.release()
    return path


@pytest.fixture(scope='session',autouse=True)
def qt_application_lifetime():
    """Destroy test widgets before PySide's interpreter-exit cleanup.

    A session-owned application and explicit DeferredDelete processing avoid
    leaving Python callback/widget cycles for unordered native atexit teardown.
    This does not suppress worker failures or force-terminate running threads.
    """
    import os
    import gc
    import time
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtCore import QCoreApplication,QEvent,QThread
    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid
    app=QApplication.instance() or QApplication([])
    yield app
    widgets=list(app.topLevelWidgets())
    for widget in widgets:
        if isValid(widget):widget.close()
    deadline=time.monotonic()+5
    active=[]
    while time.monotonic()<deadline:
        app.processEvents()
        active=[thread for widget in widgets if isValid(widget)
                for thread in widget.findChildren(QThread) if isValid(thread) and thread.isRunning()]
        if not active:break
        time.sleep(.005)
    if active:pytest.fail('Qt test workers did not shut down during normal widget cleanup')
    for widget in widgets:
        if isValid(widget):widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def no_os_camera_permission_prompts(monkeypatch):
    """UI component tests use fake consent; native/on-device acceptance is separate."""
    from PySide6.QtCore import Qt
    from sentinal.interface.camera_permission import QtCameraPermissionBackend
    monkeypatch.setattr(QtCameraPermissionBackend,'check',lambda self:Qt.PermissionStatus.Granted)
    def unexpected_request(*_):raise AssertionError('Automated unit tests must not request real OS camera permission')
    monkeypatch.setattr(QtCameraPermissionBackend,'request',unexpected_request)
