"""Stable-identity contracts use fakes; hardware results are separate evidence."""
import sys
from types import SimpleNamespace

import pytest

from sentinal.vision.camera_manager import CameraInfo, discover_cameras
from sentinal.vision.video_source import SourceSpec, VideoSource, VideoSourceError


def test_builtin_classification_does_not_treat_continuity_as_mac_camera():
    assert CameraInfo(0, 'MacBook Air Camera').is_builtin
    assert CameraInfo(4, 'FaceTime HD Camera').is_builtin
    assert not CameraInfo(1, 'iPhone FaceTime Camera').is_builtin
    assert CameraInfo(1, 'Bhupesh’s Iphone Camera').category == 'Phone camera'
    assert CameraInfo(4, 'USB webcam').category == 'External camera'


@pytest.mark.parametrize('bad', ['0', 'GG', 'aa bb', '00\n', 7, None])
def test_invalid_stable_identity_is_rejected(bad):
    with pytest.raises(ValueError, match='identity'):
        SourceSpec('camera', 0, camera_device_id=bad)


def test_identity_is_canonical_and_does_not_depend_on_display_index():
    a = SourceSpec('camera', 0, camera_device_id='AABB', camera_name='Selected Mac camera')
    b = SourceSpec('camera', 7, camera_device_id='aabb', camera_name='Selected Mac camera')
    assert a.camera_key == b.camera_key == 'aabb'
    assert a.description == 'Selected Mac camera'
    assert 'aabb' not in repr(a)
    with pytest.raises(ValueError):
        SourceSpec('file', '/example.mp4', camera_device_id='aabb')


def test_macos_index_only_fails_without_opening_system_default(monkeypatch):
    from sentinal.vision import video_source
    opened = []
    monkeypatch.setattr(video_source.sys, 'platform', 'darwin')
    monkeypatch.setattr(video_source.cv2, 'VideoCapture', lambda *a: opened.append(a))
    source = VideoSource(SourceSpec('camera', 0))
    with pytest.raises(VideoSourceError, match='named camera'):
        source.open()
    assert not opened and source.state == 'error'
    assert not source._owns_camera


def test_exact_camera_lease_survives_reorder_and_releases(monkeypatch):
    from sentinal.vision import qt_camera
    class ExactCapture:
        def __init__(self, device_id, *args):
            assert device_id == 'aabb'
        def isOpened(self): return True
        def set(self, *a): return False
        def get(self, *a): return 0
        def release(self): pass
    monkeypatch.setattr(qt_camera, 'QtCameraCapture', ExactCapture)
    a = VideoSource(SourceSpec('camera', 0, camera_device_id='aabb')).open()
    b = VideoSource(SourceSpec('camera', 9, camera_device_id='aabb'))
    try:
        with pytest.raises(VideoSourceError, match='already open'):
            b.open()
    finally:
        a.close()
    b.open()
    b.close()


def test_missing_exact_device_fails_before_constructing_a_camera(monkeypatch):
    from sentinal.vision.qt_camera import CameraCaptureError, QtCameraCapture
    from PySide6 import QtMultimedia
    opened = []
    other = SimpleNamespace(id=lambda: b'other-camera')
    monkeypatch.setattr(QtMultimedia, 'QMediaDevices', SimpleNamespace(videoInputs=lambda: [other]))
    monkeypatch.setattr(QtMultimedia, 'QCamera', lambda *args: opened.append(args))
    with pytest.raises(CameraCaptureError, match='no longer available'):
        QtCameraCapture('73656c6563746564')
    assert not opened


def test_discovery_is_passive_and_reports_stable_ids(monkeypatch):
    from PySide6 import QtMultimedia
    a = SimpleNamespace(id=lambda: b'Mac', description=lambda: 'MacBook Air Camera')
    b = SimpleNamespace(id=lambda: b'Phone', description=lambda: 'iPhone camera')
    monkeypatch.setattr(QtMultimedia, 'QMediaDevices', SimpleNamespace(
        videoInputs=lambda: [b, a], defaultVideoInput=lambda: b))
    devices = discover_cameras()
    assert [d.device_id for d in devices] == [b'Phone'.hex(), b'Mac'.hex()]
    assert devices[1].is_builtin and not devices[0].is_builtin
