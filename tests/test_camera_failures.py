"""Capture failure simulations; these do not establish real camera access."""
import pytest

from sentinal.vision import video_source
from sentinal.vision.video_source import SourceSpec, VideoSource, VideoSourceError


class FakeCamera:
    instances = []
    def __init__(self, *args):
        self.released = False
        self.__class__.instances.append(self)
    def isOpened(self):
        return True
    def set(self, *args):
        return False
    def get(self, prop):
        return 0.0
    def read(self):
        return False, None
    def release(self):
        self.released = True


def test_camera_has_exclusive_owner_and_failed_read_releases(monkeypatch):
    monkeypatch.setattr(video_source.sys, "platform", "linux")
    FakeCamera.instances.clear()
    monkeypatch.setattr(video_source.cv2, "VideoCapture", FakeCamera)
    first, second = VideoSource(SourceSpec("camera", 70)), VideoSource(SourceSpec("camera", 70))
    try:
        first.open()
        with pytest.raises(VideoSourceError, match="already open"):
            second.open()
        assert len(FakeCamera.instances) == 1
        with pytest.raises(VideoSourceError, match="stopped delivering"):
            first.read()
        assert first.state == "error"
        assert FakeCamera.instances[0].released
        second.open()  # Failed first read relinquished the exclusive camera lease.
        assert second.state == "open"
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("kind,value", [("network", "https://example.invalid"), ("camera", -1),
                                       ("camera", "0"), ("camera", True), ("file", "")])
def test_source_spec_rejects_unsupported_inputs(kind, value):
    with pytest.raises(ValueError):
        SourceSpec(kind, value)
