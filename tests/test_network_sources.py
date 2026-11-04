"""Stream validation and decoder contracts; mocks are not live-camera evidence."""
import math
import numpy as np
import pytest

from sentinal.vision.video_source import SourceSpec, VideoSource, VideoSourceError


@pytest.mark.parametrize('url', [
    '', 'file:///tmp/video.mp4', 'ftp://camera/stream', '/tmp/video.mp4',
    'rtsp://', 'http://camera:99999/feed', 'http://camera:0/feed',
    'http://camera:abc/feed', 'http://camera/a b', 'rtsp://camera/\npath',
    'rtsp://camera/\x00path', 'http://camera/feed#fragment',
])
def test_stream_addresses_are_explicit_and_validated_without_echo(url):
    with pytest.raises(ValueError) as error:
        SourceSpec('stream', url)
    assert 'Enter a valid' in str(error.value)
    assert 'password' not in str(error.value)


def test_labels_repr_hide_credentials_path_and_query():
    spec = SourceSpec('stream', 'rtsp://alice:private%3Apassword@192.168.1.30:554/sensitive/room?token=secret')
    assert spec.description == 'RTSP camera · 192.168.1.30:554'
    for value in ('alice', 'private', 'password', 'sensitive', 'token', 'secret'):
        assert value not in repr(spec)
    assert SourceSpec('stream', 'https://[::1]:8443/feed').description == 'HTTPS camera · [::1]:8443'


def test_stream_decoder_uses_open_and_read_timeouts(monkeypatch):
    from sentinal.vision import video_source
    calls = []
    class Capture:
        def __init__(self, *args):
            calls.append(args)
            self.released = False
        def isOpened(self): return True
        def get(self, prop):
            return 25.0 if prop == video_source.cv2.CAP_PROP_FPS else 1000.0
        def read(self): return True, np.ones((12, 16, 3), dtype=np.uint8)
        def release(self): self.released = True
    monkeypatch.setattr(video_source.cv2, 'VideoCapture', Capture)
    spec = SourceSpec('stream', 'https://camera.example/feed')
    source = VideoSource(spec, open_timeout_ms=4000, read_timeout_ms=1200)
    source.open()
    try:
        assert calls[0] == (spec.value, video_source.cv2.CAP_FFMPEG, [
            video_source.cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000,
            video_source.cv2.CAP_PROP_READ_TIMEOUT_MSEC, 1200])
        assert source.frame_count == 0 and source.duration_s is None
        assert source.read().shape == (12, 16, 3)
        assert source.source_time_s >= 0
    finally:
        capture = source.capture
        source.close()
    assert capture.released


def test_stream_exception_never_exposes_authenticated_url(monkeypatch, caplog):
    from sentinal.vision import video_source
    url = 'rtsp://alice:supersecret@127.0.0.1/private?token=hidden'
    def fail(*args):
        raise RuntimeError('backend message includes ' + url)
    monkeypatch.setattr(video_source.cv2, 'VideoCapture', fail)
    source = VideoSource(SourceSpec('stream', url))
    with pytest.raises(VideoSourceError) as error:
        source.open()
    assert 'supersecret' not in str(error.value) + caplog.text
    assert 'token=hidden' not in str(error.value) + caplog.text
    assert source.state == 'error' and source.capture is None


def test_real_file_seek_updates_next_frame_index(synthetic_video):
    source = VideoSource(SourceSpec('file', str(synthetic_video))).open()
    try:
        assert source.duration_s == pytest.approx(.5)
        source.read()
        assert source.seek(.3) == pytest.approx(.3)
        assert source.frame_index == 3
        assert source.read() is not None
        assert source.frame_index == 4
        assert source.source_time_s == pytest.approx(.3, abs=.02)
    finally:
        source.close()


@pytest.mark.parametrize('value', [-1, math.nan, math.inf, True, '3'])
def test_seek_rejects_invalid_media_positions(synthetic_video, value):
    with VideoSource(SourceSpec('file', str(synthetic_video))) as source:
        with pytest.raises(ValueError):
            source.seek(value)
