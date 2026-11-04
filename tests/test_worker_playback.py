"""Control-state regressions with explicit fake inference, not model proof."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
import time

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from sentinal.config import AppConfig
from sentinal.vision import inference_worker as module
from sentinal.vision.types import FramePacket, utc_now
from sentinal.vision.video_source import SourceSpec, VideoSourceError


def wait(app, predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.003)
    raise AssertionError('Worker control transition timed out')


class FakePipeline:
    def __init__(self, config):
        self.config = config
        self.detector = SimpleNamespace(config=config)
        self.source = None
        self.starts = []
        self.seeks = []
        self.steps = 0
    def start(self, spec):
        self.session = str(uuid4())
        self.starts.append(self.session)
        self.source = SimpleNamespace(spec=spec, fps=40., frame_count=400, source_time_s=0.)
        self.index = 0
    def step(self, **kwargs):
        time.sleep(.003)
        if self.source.spec.kind == 'stream' and len(self.starts) == 1:
            raise VideoSourceError('Explicit synthetic feed interruption')
        self.steps += 1
        self.index += 1
        self.source.source_time_s = self.index / 40
        return FramePacket(np.zeros((48, 64, 3), dtype=np.uint8), (), self.session,
                           self.source.spec.description, self.index, utc_now(),
                           self.source.source_time_s, 40., 1., 1., 'cpu')
    def seek(self, seconds):
        self.seeks.append(seconds)
        self.index = round(seconds * 40)
        self.source.source_time_s = seconds
        self.session = str(uuid4())
        return seconds
    def stop(self):
        self.source = None


class FakeEvents:
    def __init__(self, config):pass
    def process(self, packet, enabled=False):return None
    def close(self):pass


@pytest.fixture
def worker(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module, 'VisionPipeline', FakePipeline)
    monkeypatch.setattr(module, 'EventManager', FakeEvents)
    instance = module.InferenceWorker(AppConfig(stream_reconnect_delay_s=.1))
    states = []
    instance.state_changed.connect(lambda state, _: states.append(state))
    instance.start()
    yield app, instance, states
    instance.request_shutdown()
    wait(app, lambda: not instance.isRunning())
    instance.wait()


def test_pause_seek_preview_and_resume_do_not_reload_model(worker):
    app, thread, states = worker
    thread.request_start(SourceSpec('file', '/explicit-unit-test.mp4'))
    wait(app, lambda: thread.pipeline is not None and thread.pipeline.steps >= 2)
    identity = id(thread.pipeline)
    thread.request_pause(True)
    wait(app, lambda: states and states[-1] == 'paused')
    count = thread.pipeline.steps
    deadline = time.monotonic() + .08
    while time.monotonic() < deadline:
        app.processEvents();time.sleep(.003)
    assert thread.pipeline.steps == count
    session = thread.pipeline.session
    thread.request_seek(2.5)
    wait(app, lambda: thread.pipeline.steps == count + 1)
    assert thread.pipeline.session != session
    assert thread.pipeline.seeks == [2.5]
    assert states[-1] == 'paused'
    packet = thread.take_latest()
    assert packet.source_time_s >= 2.5
    thread.request_pause(False)
    wait(app, lambda: thread.pipeline.steps >= count + 3)
    assert id(thread.pipeline) == identity


def test_network_interruption_reconnects_as_new_session(worker):
    app, thread, states = worker
    thread.request_start(SourceSpec('stream', 'http://127.0.0.1:12345/unit-test'))
    wait(app, lambda: thread.pipeline is not None and thread.pipeline.steps >= 2)
    assert len(thread.pipeline.starts) == 2
    assert len(set(thread.pipeline.starts)) == 2
    assert 'reconnecting' in states
    assert states[-1] == 'running'
    thread.request_stop()
    wait(app, lambda: states[-1] == 'stopped')
    assert thread.pipeline.source is None


def test_resolution_changes_take_effect_in_existing_detector(worker):
    app, thread, states = worker
    thread.request_start(SourceSpec('file', '/explicit-unit-test.mp4'))
    wait(app, lambda: thread.pipeline is not None and thread.pipeline.steps >= 2)
    identity = id(thread.pipeline.detector)
    thread.set_options(image_size=320)
    wait(app, lambda: thread.pipeline.detector.config.image_size == 320)
    assert id(thread.pipeline.detector) == identity


def test_slider_commands_coalesce_and_stop_supersedes_them():
    thread = module.InferenceWorker(AppConfig())
    for i in range(2000):thread.request_seek(i / 10)
    assert thread._commands.qsize() == 1
    assert thread._commands.queue[-1] == ('seek', 199.9)
    thread.request_stop()
    assert thread._commands.qsize() == 1
    assert thread._commands.queue[-1][0] == 'stop'


@pytest.mark.parametrize('values', [
    {'stream_open_timeout_ms': True}, {'stream_read_timeout_ms': 249},
    {'stream_open_timeout_ms': 30001}, {'stream_reconnect_attempts': -1},
    {'stream_reconnect_attempts': 2.5}, {'stream_reconnect_delay_s': float('nan')},
])
def test_stream_configuration_rejects_unsafe_timeouts(values):
    with pytest.raises(ValueError):AppConfig(**values)


def test_model_changes_only_at_new_session_boundary(worker):
    app, thread, states = worker
    spec = SourceSpec('file', '/explicit-unit-test.mp4')
    thread.request_start(spec)
    wait(app, lambda: thread.pipeline is not None and thread.pipeline.steps >= 2)
    original = thread.pipeline
    thread.set_options(model_path='models/yolov8n-oiv7.pt')
    assert thread.pipeline is original
    thread.request_stop()
    wait(app, lambda: states[-1] == 'stopped')
    thread.request_start(spec)
    wait(app, lambda: thread.pipeline is not original and thread.pipeline.steps >= 2)
    assert thread.pipeline.config.model_path == 'models/yolov8n-oiv7.pt'
    thread.request_stop()
    wait(app, lambda: states[-1] == 'stopped')
    same_model = thread.pipeline
    thread.request_start(spec)
    wait(app, lambda: states[-1] == 'running')
    assert thread.pipeline is same_model
