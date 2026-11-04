"""UI/worker contract tests with synthetic packets, not proof of real inference."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from sentinal.config import AppConfig
from sentinal.vision.types import Detection, FramePacket, utc_now
from sentinal.vision.video_source import VideoSourceError
from sentinal.interface.video_panel import VideoPanel
from sentinal.interface.main_window import MainWindow
from sentinal.vision import inference_worker


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def spin(app, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("Qt state transition timed out")


def packet(index=1):
    return FramePacket(
        np.zeros((480, 640, 3), dtype=np.uint8),
        (Detection(0, "person", .9, (100, 100, 300, 400), 7),),
        "synthetic-session", "synthetic-test-only", index, utc_now(), index / 30,
        12.5, 50.0, 52.0, "cpu",
    )


def test_annotation_render_and_toggles(qt_app):
    panel = VideoPanel()
    panel.resize(640, 480)
    sample = packet()
    panel.set_packet(sample)
    panel.show()
    qt_app.processEvents()
    rendered = panel.grab().toImage()
    # Source x=100 maps near x=101 after the aspect-preserving 2px margin.
    assert any(rendered.pixelColor(x, 200).blue() > 150 for x in range(98, 105))
    assert not sample.frame.any(), "Annotations must not mutate source frames"
    panel.set_annotations(False, False, False)
    qt_app.processEvents()
    plain = panel.grab().toImage()
    assert all(plain.pixelColor(x, 200).blue() == 0 for x in range(98, 105))
    panel.close()


class SyntheticPipeline:
    instances = []

    def __init__(self, config):
        self.active = False
        self.frame = 0
        self.stops = 0
        self.__class__.instances.append(self)

    def start(self, spec):
        if spec.kind == "file" and "missing" in str(spec.value):
            raise VideoSourceError("The selected video does not exist.")
        self.active = True
        self.frame = 0

    def step(self, **kwargs):
        assert self.active
        time.sleep(.004)
        self.frame += 1
        return packet(self.frame)

    def stop(self):
        self.active = False
        self.stops += 1


class SyntheticEvents:
    instances = []

    def __init__(self, config):
        self.closes = 0
        self.__class__.instances.append(self)

    def process(self, packet, enabled):
        return "Synthetic database write failure" if enabled else None

    def close(self):
        self.closes += 1


@pytest.fixture
def dashboard(qt_app, monkeypatch):
    SyntheticPipeline.instances.clear()
    SyntheticEvents.instances.clear()
    monkeypatch.setattr(inference_worker, "VisionPipeline", SyntheticPipeline)
    monkeypatch.setattr(inference_worker, "EventManager", SyntheticEvents)
    window = MainWindow(AppConfig())
    window.show()
    yield window
    window.close()
    spin(qt_app, lambda: not window.worker.isRunning())
    qt_app.processEvents()


def test_start_stop_reuse_and_metadata_failure(qt_app, dashboard):
    window = dashboard
    assert not window.metadata_toggle.isChecked()
    assert not SyntheticPipeline.instances, "Startup must not open a camera or load inference"
    window.load_video("/synthetic/fixture.mp4")
    window.start_monitoring()
    spin(qt_app, lambda: window.last_packet is not None)
    assert window._state == "running"
    assert window.statistics.values["people"].text() == "1"
    assert window.statistics.values["tracked"].text() == "1"
    window.metadata_toggle.setChecked(True)
    spin(qt_app, lambda: not window.metadata_toggle.isChecked())
    assert "disabled" in window.error_banner.text()
    closes_before_stop = SyntheticEvents.instances[0].closes
    window.stop_monitoring()
    spin(qt_app, lambda: window._state == "stopped")
    assert not SyntheticPipeline.instances[0].active
    assert SyntheticEvents.instances[0].closes > closes_before_stop
    window.start_monitoring()
    spin(qt_app, lambda: window.last_packet is not None and window._state == "running")
    assert len(SyntheticPipeline.instances) == 1, "The model-owning pipeline should be reused"
    assert not window.start_button.isEnabled()
    window.stop_monitoring()
    spin(qt_app, lambda: window._state == "stopped")


def test_failure_releases_source_and_recovers(qt_app, dashboard):
    window = dashboard
    window.load_video("/synthetic/missing.mp4")
    window.start_monitoring()
    spin(qt_app, lambda: window._state == "error")
    assert "does not exist" in window.error_banner.text()
    assert window.start_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert not SyntheticPipeline.instances[0].active
    window.load_video("/synthetic/valid.mp4")
    window.start_monitoring()
    spin(qt_app, lambda: window.last_packet is not None)
    assert window._state == "running"
