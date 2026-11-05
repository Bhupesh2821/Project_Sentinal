"""Process mailbox/failure simulations and actual loopback MJPEG decoding.

Synthetic process frames establish lifecycle semantics only. The HTTP test
serves actual recorded vtest frames; it is network decoding evidence, not a
physical IP-camera or model-accuracy test. No camera is opened here.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
import os
import threading
import time

import cv2
import numpy as np
import pytest

from sentinal.config import ROOT
from sentinal.vision.live_capture import LiveVideoSource
from sentinal.vision.video_source import SourceSpec, VideoSource, VideoSourceError


def frame_process(spec, width, height, open_timeout, read_timeout, memory_name,
                  metadata, lock, ready, stop, status):
    memory = SharedMemory(name=memory_name)
    try:
        status.put(('opened', 100.0))
        sequence = 0
        while not stop.wait(.005):
            sequence += 1
            with lock:
                frame = np.ndarray((24, 32, 3), dtype=np.uint8, buffer=memory.buf)
                frame[:] = sequence % 255
                metadata[:] = [sequence, 24, 32, sequence / 100, time.monotonic(), 100]
            ready.set()
    finally:
        memory.close()
        status.cancel_join_thread()


def stalled_process(spec, width, height, open_timeout, read_timeout, memory_name,
                    metadata, lock, ready, stop, status):
    status.put(('opened', 24.0))
    # Deliberately simulate a driver that cannot notice the normal stop event.
    while True:
        time.sleep(100)


def no_frame_process(spec, width, height, open_timeout, read_timeout, memory_name,
                     metadata, lock, ready, stop, status):
    status.put(('opened', 24.0))
    stop.wait(10)


def test_live_mailbox_is_fresh_and_counts_dropped_capture_frames():
    source = LiveVideoSource(SourceSpec('camera', 71), _capture_target=frame_process)
    source.open()
    try:
        first = source.read()
        index = source.frame_index
        first[:] = 0  # The returned image is detached from shared capture memory.
        time.sleep(.08)
        second = source.read()
        assert source.frame_index > index
        assert source.dropped_frames > 0
        assert source.frame_age_ms < 1000
        assert second.shape == (24, 32, 3) and np.any(second)
    finally:
        name = source._memory.name
        source.close()
    assert source.capture is None and source.state == 'closed'
    with pytest.raises(FileNotFoundError):
        SharedMemory(name=name)


def test_stalled_native_reader_can_be_stopped_within_bound():
    source = LiveVideoSource(SourceSpec('camera', 72), _capture_target=stalled_process)
    source.open()
    started = time.monotonic()
    source.close()
    assert time.monotonic() - started < 2.5
    assert source.capture is None
    # A terminated child relinquishes the parent-side camera lease.
    replacement = LiveVideoSource(SourceSpec('camera', 72), _capture_target=frame_process)
    replacement.open()
    replacement.close()


def test_live_source_times_out_instead_of_repeating_a_stale_image():
    source = LiveVideoSource(SourceSpec('camera', 73), read_timeout_ms=100, _capture_target=no_frame_process)
    source.open()
    with pytest.raises(VideoSourceError, match='fresh frames'):
        source.read()
    assert source.capture is None and source.state == 'error'


def test_live_and_synchronous_capture_share_camera_exclusivity(monkeypatch):
    source = LiveVideoSource(SourceSpec('camera', 74), _capture_target=frame_process).open()
    try:
        with pytest.raises(VideoSourceError, match='already open'):
            VideoSource(SourceSpec('camera', 74)).open()
    finally:
        source.close()


def test_actual_http_mjpeg_connection_decodes_real_recorded_frames():
    fixture = ROOT / 'tests/fixtures/vtest.avi'
    assert fixture.is_file()
    capture = cv2.VideoCapture(str(fixture))
    images = []
    try:
        for _ in range(8):
            ok, frame = capture.read()
            assert ok
            ok, encoded = cv2.imencode('.jpg', frame)
            assert ok
            images.append(encoded.tobytes())
    finally:
        capture.release()
    done = threading.Event()
    class Feed(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            index = 0
            try:
                while not done.is_set():
                    image = images[index % len(images)]
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(len(image)).encode() + b'\r\n\r\n' + image + b'\r\n')
                    self.wfile.flush()
                    index += 1
                    done.wait(.02)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Feed)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = LiveVideoSource(SourceSpec('stream', f'http://127.0.0.1:{server.server_port}/feed'), open_timeout_ms=3000, read_timeout_ms=1000)
    try:
        source.open()
        frames = [source.read() for _ in range(3)]
        assert all(frame.shape == (576, 768, 3) for frame in frames)
        assert source.frame_index >= 3
        assert source.frame_age_ms < 1000
        assert source.description.startswith('HTTP camera · 127.0.0.1:')
    finally:
        source.close()
        done.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_partial_initialization_frees_memory_and_camera_lease(monkeypatch):
    from sentinal.vision import live_capture, video_source
    original = live_capture.SharedMemory
    allocated = []
    def tracked_memory(*args, **kwargs):
        memory = original(*args, **kwargs)
        allocated.append(memory.name)
        return memory
    class BrokenContext:
        def Array(self, *args, **kwargs):
            raise OSError('simulated metadata allocation failure')
    monkeypatch.setattr(live_capture, 'SharedMemory', tracked_memory)
    monkeypatch.setattr(live_capture.mp, 'get_context', lambda kind: BrokenContext())
    source = LiveVideoSource(SourceSpec('camera', 75))
    with pytest.raises(VideoSourceError):
        source.open()
    assert source.state == 'error' and source.capture is None and source._memory is None
    assert 75 not in video_source._active_cameras
    for name in allocated:
        with pytest.raises(FileNotFoundError):
            original(name=name)


def test_already_unlinked_memory_does_not_prevent_camera_release():
    from sentinal.vision import video_source
    source = LiveVideoSource(SourceSpec('camera', 76), _capture_target=frame_process).open()
    source.read()
    source._memory.unlink()
    source.close()
    source.close()
    assert source.state == 'closed' and source.capture is None
    assert 76 not in video_source._active_cameras
