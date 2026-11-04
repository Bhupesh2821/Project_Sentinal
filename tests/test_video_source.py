"""Synthetic encoded video proves capture state/codec handling, not AI accuracy."""
from pathlib import Path

import pytest

from sentinal.vision.video_source import SourceSpec, VideoSource, VideoSourceError


def test_video_state_eof_restart_and_resource_release(synthetic_video):
    source = VideoSource(SourceSpec("file", str(synthetic_video)))
    assert source.state == "closed"
    source.open()
    try:
        assert source.state == "open"
        assert source.fps == pytest.approx(10, abs=0.5)
        frames = []
        while True:
            frame = source.read()
            if frame is None:
                break
            frames.append(frame)
        assert len(frames) == 5
        assert all(frame.shape[:2] == (48, 64) for frame in frames)
        assert source.frame_index == 5
        assert source.state == "eof"
        source.restart()
        assert source.state == "open"
        assert source.read() is not None
        assert source.frame_index == 1
    finally:
        source.close()
    assert source.state == "closed"
    source.close()  # An idempotent close is required for shutdown paths.


def test_repeated_open_close_does_not_leave_competing_capture(synthetic_video):
    source = VideoSource(SourceSpec("file", str(synthetic_video)))
    for _ in range(4):
        source.open()
        assert source.read() is not None
        source.close()
        assert source.state == "closed"


def test_missing_file_has_understandable_error(tmp_path):
    source = VideoSource(SourceSpec("file", str(tmp_path / "does-not-exist.mp4")))
    with pytest.raises(VideoSourceError):
        source.open()
    assert source.state == "error"
    source.close()


def test_corrupt_file_has_understandable_error_and_releases_handle(tmp_path):
    path = tmp_path / "corrupt.mp4"
    path.write_bytes(b"This is not a video codec or container")
    source = VideoSource(SourceSpec("file", str(path)))
    with pytest.raises(VideoSourceError):
        source.open()
    assert source.state == "error"
    source.close()
    assert source.state == "closed"


def test_closed_source_does_not_silently_generate_video(synthetic_video):
    source = VideoSource(SourceSpec("file", str(synthetic_video)))
    with pytest.raises(VideoSourceError):
        source.read()


def test_missing_camera_raises_instead_of_faking_frames(monkeypatch):
    from sentinal.vision import video_source
    monkeypatch.setattr(video_source.sys, "platform", "linux")
    class UnavailableCapture:
        def __init__(self, *args, **kwargs):
            self.released = False
        def isOpened(self):
            return False
        def release(self):
            self.released = True
    monkeypatch.setattr(video_source.cv2, "VideoCapture", UnavailableCapture)
    source = VideoSource(SourceSpec("camera", 0))
    with pytest.raises(VideoSourceError):
        source.open()
    assert source.state == "error"
    source.close()
