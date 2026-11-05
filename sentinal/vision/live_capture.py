"""Newest-frame capture in an isolated process with bounded memory and stop.

A fixed shared-memory slot carries pixels. Only tiny status messages use a
queue, so stopping a driver cannot strand a partially serialized video frame.
No inference, footage files or audio recording occur in the capture process.
"""
import logging
import multiprocessing as mp
from multiprocessing.shared_memory import SharedMemory
import os
import queue
from time import monotonic, sleep

import cv2
import numpy as np

from .video_source import VideoSource, VideoSourceError, _claim_camera, _release_camera

log = logging.getLogger(__name__)
_MAX_EDGE = 1920
_MAX_BYTES = _MAX_EDGE * _MAX_EDGE * 3


class _SignalFlag:
    """Nonlocking IPC hint: child death cannot strand an Event condition lock."""
    def __init__(self, context):
        self._value = context.Value("b", 0, lock=False)

    def set(self):
        self._value.value = 1

    def clear(self):
        self._value.value = 0

    def is_set(self):
        return bool(self._value.value)

    def wait(self, timeout=None):
        deadline = None if timeout is None else monotonic() + max(0.0, timeout)
        while not self.is_set():
            if deadline is not None and monotonic() >= deadline:
                return False
            sleep(.005 if deadline is None else min(.005, max(0.0, deadline - monotonic())))
        return True


def _status_put(status, message):
    try:
        status.put_nowait(message)
    except queue.Full:
        pass


def _capture_child(spec, width, height, open_timeout_ms, read_timeout_ms,
                   memory_name, metadata, lock, ready, stop, status):
    # Native FFmpeg can echo authenticated URLs. Isolate its stderr here.
    if spec.kind == "stream":
        descriptor = os.open(os.devnull, os.O_WRONLY)
        os.dup2(descriptor, 2)
        os.close(descriptor)
    memory = source = None
    try:
        memory = SharedMemory(name=memory_name)
        source = VideoSource(spec, width, height, open_timeout_ms, read_timeout_ms)
        source.open()
        _status_put(status, ("opened", source.fps))
        while not stop.is_set():
            frame = source.read()
            grabbed_at = monotonic()
            if frame is None or frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
                raise VideoSourceError("The live source returned an unsupported image format.")
            height_now, width_now = frame.shape[:2]
            if max(height_now, width_now) > _MAX_EDGE:
                scale = _MAX_EDGE / max(height_now, width_now)
                frame = cv2.resize(frame, (max(1, int(width_now * scale)), max(1, int(height_now * scale))), interpolation=cv2.INTER_AREA)
                height_now, width_now = frame.shape[:2]
            if not lock.acquire(timeout=.2):
                continue
            try:
                target = np.ndarray((height_now, width_now, 3), dtype=np.uint8, buffer=memory.buf)
                np.copyto(target, frame)
                metadata[:] = [source.frame_index, height_now, width_now,
                               source.source_time_s, grabbed_at, source.fps]
            finally:
                lock.release()
            ready.set()
    except Exception as exc:
        # Never transmit raw driver exceptions, endpoints or tracebacks.
        message = ("Network camera stopped or could not connect. Check its address, credentials and connection."
                   if spec.kind == "stream" else
                   "Camera unavailable or stopped delivering frames. Check its connection and macOS camera permission.")
        if spec.kind == "camera" and isinstance(exc, VideoSourceError):
            message = str(exc)
        _status_put(status, ("error", message))
        ready.set()
    finally:
        if source is not None:
            source.close()
        if memory is not None:
            memory.close()
        _status_put(status, ("closed", None))
        status.cancel_join_thread()


class LiveVideoSource:
    """Fresh live frames with the VideoSource API and no decoder on the UI loop.

    The longer live-frame edge is capped at 1920 before entering the mailbox.
    Returned coordinates therefore describe the returned frame dimensions.
    """
    def __init__(self, spec, width=640, height=480, open_timeout_ms=5000,
                 read_timeout_ms=2000, *, _capture_target=None):
        if spec.kind not in {"camera", "stream"}:
            raise ValueError("Live capture requires a camera or network stream")
        if any(type(v) is not int or not 1 <= v <= 120000 for v in (open_timeout_ms, read_timeout_ms)):
            raise ValueError("Capture timeouts must be positive whole milliseconds up to 120000")
        self.spec, self.width, self.height = spec, width, height
        self.open_timeout_ms, self.read_timeout_ms = open_timeout_ms, read_timeout_ms
        self.state = "closed"
        self.capture = None
        self.fps = self.source_time_s = self.frame_age_ms = 0.0
        self.frame_count = self.frame_index = self.dropped_frames = 0
        self._owns_camera = False
        self._memory = None
        self._metadata = self._lock = self._ready = self._stop = self._status = None
        self._capture_target = _capture_target or _capture_child

    @property
    def description(self):
        return self.spec.description

    @property
    def duration_s(self):
        return None

    def open(self):
        if self.state == "open":
            return self
        self.close()
        self.frame_index = self.dropped_frames = 0
        self.source_time_s = self.frame_age_ms = 0.0
        try:
            if self.spec.kind == "camera":
                _claim_camera(self.spec.camera_key)
                self._owns_camera = True
            context = mp.get_context("spawn")
            self._memory = SharedMemory(create=True, size=_MAX_BYTES)
            self._metadata = context.Array("d", 6, lock=False)
            self._lock = context.Lock()
            self._ready, self._stop = _SignalFlag(context), _SignalFlag(context)
            self._status = context.Queue(maxsize=4)
            self.capture = context.Process(target=self._capture_target, args=(
                self.spec, self.width, self.height, self.open_timeout_ms, self.read_timeout_ms,
                self._memory.name, self._metadata, self._lock, self._ready, self._stop, self._status),
                name="SENTINAL capture", daemon=True)
            self.capture.start()
            deadline = monotonic() + self.open_timeout_ms / 1000 + 2.0
            while monotonic() < deadline:
                try:
                    kind, value = self._status.get(timeout=min(.1, max(.001, deadline - monotonic())))
                except queue.Empty:
                    if not self.capture.is_alive():
                        raise VideoSourceError("The live capture process could not start. Check camera permission or the stream connection.")
                    continue
                if kind == "opened":
                    self.fps = float(value)
                    self.state = "open"
                    return self
                if kind == "error":
                    raise VideoSourceError(value)
            raise VideoSourceError("Opening the live source timed out. Check its connection, then try again.")
        except Exception as exc:
            self.close()
            self.state = "error"
            if isinstance(exc, VideoSourceError):
                raise
            raise VideoSourceError("The live capture process could not start. Close other camera apps and try again.") from None

    def _error_if_any(self):
        if self._status is None:
            return
        while True:
            try:
                kind, value = self._status.get_nowait()
            except queue.Empty:
                return
            if kind == "error":
                raise VideoSourceError(value)

    def read(self):
        if self.state != "open" or self.capture is None:
            raise VideoSourceError("No live source is open. Start monitoring first.")
        deadline = monotonic() + self.read_timeout_ms / 1000
        try:
            while monotonic() < deadline:
                self._error_if_any()
                if not self.capture.is_alive():
                    raise VideoSourceError("The live source disconnected. Check its connection and start again.")
                if not self._ready.wait(min(.1, max(0, deadline - monotonic()))):
                    continue
                if not self._lock.acquire(timeout=min(.2, max(.001, deadline - monotonic()))):
                    continue
                try:
                    sequence, height, width, media_time, captured_at, fps = self._metadata[:]
                    self._ready.clear()
                    if int(sequence) <= self.frame_index:
                        continue
                    height, width, sequence = int(height), int(width), int(sequence)
                    if not 0 < height <= _MAX_EDGE or not 0 < width <= _MAX_EDGE:
                        raise VideoSourceError("The live source returned an invalid frame size.")
                    age = max(0.0, monotonic() - captured_at)
                    if age > self.read_timeout_ms / 1000:
                        raise VideoSourceError("The live source stopped delivering fresh frames. Check its connection.")
                    frame = np.ndarray((height, width, 3), dtype=np.uint8, buffer=self._memory.buf).copy()
                finally:
                    self._lock.release()
                self.dropped_frames += max(0, sequence - self.frame_index - 1)
                self.frame_index, self.source_time_s, self.fps = sequence, float(media_time), float(fps)
                self.frame_age_ms = age * 1000
                return frame
            raise VideoSourceError("The live source stopped delivering fresh frames. Check its connection.")
        except Exception as exc:
            self.close()
            self.state = "error"
            if isinstance(exc, VideoSourceError):
                raise
            raise VideoSourceError("The live source stopped unexpectedly. Check its connection and try again.") from None

    def close(self):
        process = self.capture
        if self._stop is not None:
            self._stop.set()
        if process is not None and process.pid is not None:
            process.join(timeout=.4)
            if process.is_alive():
                process.terminate()
                process.join(timeout=.8)
            if process.is_alive():
                process.kill()
                process.join(timeout=.5)
            if process.is_alive():
                self.state = "error"
                raise VideoSourceError("The capture driver did not stop. Close SENTINAL before opening another session.")
        if process is not None:
            process.close()
        self.capture = None
        if self._memory is not None:
            try:
                self._memory.close()
            except BufferError:
                log.warning("A capture-memory view is still held during shutdown")
            try:
                self._memory.unlink()
            except FileNotFoundError:
                pass  # Another cleanup path has already removed the IPC name.
            self._memory = None
        if self._status is not None:
            try:
                self._status.close()
                self._status.cancel_join_thread()
            except (ValueError, OSError):
                log.warning("Capture status channel was already closed")
        self._metadata = self._lock = self._ready = self._stop = self._status = None
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
