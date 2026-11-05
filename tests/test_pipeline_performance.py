"""Pipeline orchestration tests use a fake detector, not fake camera evidence."""
import math

import pytest

from sentinal.config import AppConfig
from sentinal.vision.performance import PerformanceMeter
from sentinal.vision.types import Detection
from sentinal.vision.video_source import SourceSpec, VideoSourceError


@pytest.fixture
def fake_pipeline(monkeypatch):
    from sentinal.vision import pipeline as module
    class FakeDetector:
        def __init__(self, config):
            self.device = "cpu"
            self.last_inference_ms = 2.0
            self.resets = 0
        def load(self):
            return self
        def reset_tracking(self):
            self.resets += 1
        def infer(self, frame, confidence=None):
            return (Detection(0, "person", 0.8, (1, 1, 20, 40), 1),
                    Detection(56, "chair", 0.7, (25, 1, 50, 30), 2))
    monkeypatch.setattr(module, "YOLODetector", FakeDetector)
    return module.VisionPipeline(AppConfig())


def test_pipeline_populates_packets_and_presentation_filter(fake_pipeline, synthetic_video):
    fake_pipeline.start(SourceSpec("file", str(synthetic_video)))
    try:
        packet = fake_pipeline.step(focus_only=True)
        assert len(packet.detections) == 1
        assert packet.detections[0].label == "person"
        assert packet.frame_index == 1
        assert packet.inference_ms == 2.0
        assert packet.fps > 0
        assert packet.device == "cpu"
        assert packet.source == synthetic_video.name
        assert packet.session_id
        # Filtering one frame does not permanently remove other class capabilities.
        assert len(fake_pipeline.step(focus_only=False).detections) == 2
    finally:
        fake_pipeline.stop()


def test_pipeline_switch_resets_track_state_and_session_ids(fake_pipeline, synthetic_video):
    spec = SourceSpec("file", str(synthetic_video))
    first = fake_pipeline.start(spec)
    fake_pipeline.step()
    previous_source = fake_pipeline.source
    second = fake_pipeline.start(spec)
    assert first != second
    assert previous_source.state == "closed"
    assert fake_pipeline.detector.resets == 2
    assert fake_pipeline.step().frame_index == 1
    third = fake_pipeline.reset()
    assert len({first, second, third}) == 3
    fake_pipeline.stop()
    fake_pipeline.stop()
    assert fake_pipeline.source is None


def test_pipeline_no_start_and_missing_file_fail_cleanly(fake_pipeline, tmp_path):
    with pytest.raises(VideoSourceError):
        fake_pipeline.step()
    with pytest.raises(VideoSourceError):
        fake_pipeline.start(SourceSpec("file", str(tmp_path / "missing.mp4")))
    assert fake_pipeline.source is None
    fake_pipeline.stop()


def test_pipeline_eof_does_not_loop_without_restart(fake_pipeline, synthetic_video):
    fake_pipeline.start(SourceSpec("file", str(synthetic_video)))
    try:
        for _ in range(5):
            assert fake_pipeline.step() is not None
        assert fake_pipeline.step() is None
        assert fake_pipeline.step() is None
        fake_pipeline.reset()
        assert fake_pipeline.step().frame_index == 1
    finally:
        fake_pipeline.stop()


def test_meter_reports_actual_bounded_window_and_resets():
    meter = PerformanceMeter(window=2)
    assert meter.fps == 0
    meter.record(1.0, 1000)
    meter.record(0.05, 30)
    meter.record(0.05, 40)
    assert meter.fps == pytest.approx(20)
    assert meter.average_inference_ms == pytest.approx(35)
    assert len(meter._steps) == 2
    meter.reset()
    assert meter.fps == meter.average_inference_ms == 0


@pytest.mark.parametrize("elapsed,inference", [(-1, 1), (1, -1), (math.inf, 1), (1, math.nan)])
def test_meter_rejects_invalid_timings(elapsed, inference):
    with pytest.raises(ValueError):
        PerformanceMeter().record(elapsed, inference)
