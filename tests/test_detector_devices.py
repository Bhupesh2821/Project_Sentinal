"""Failure-path unit tests use fakes; these do not establish hardware support."""
from types import SimpleNamespace
import sys

import numpy as np
import pytest

from sentinal.config import AppConfig
from sentinal.core.device_manager import select_device
from sentinal.vision.detector import DetectorError, YOLODetector
from sentinal.vision.types import Detection


def torch_capability(available):
    return SimpleNamespace(backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: available)))


@pytest.mark.parametrize("preference,available,expected", [
    ("auto", True, "mps"), ("auto", False, "cpu"),
    ("mps", False, "cpu"), ("cpu", True, "cpu"),
])
def test_device_selection_obeys_capability(preference, available, expected):
    assert select_device(preference, torch_capability(available)) == expected


def test_capability_query_error_falls_back_to_cpu():
    def broken():
        raise RuntimeError("unit test: backend unavailable")
    fake_torch = SimpleNamespace(backends=SimpleNamespace(mps=SimpleNamespace(is_available=broken)))
    assert select_device("auto", fake_torch) == "cpu"


def test_missing_weights_fails_without_network_attempt(tmp_path):
    detector = YOLODetector(AppConfig(model_path=str(tmp_path / "missing.pt")))
    with pytest.raises(DetectorError, match="weights are missing"):
        detector.load()
    assert detector.model is None


@pytest.mark.parametrize("frame", [None, np.zeros((0, 0, 3)), np.zeros((8, 8)), np.zeros((8, 8, 4))])
def test_invalid_input_is_rejected_before_model_loading(frame):
    detector = YOLODetector(AppConfig())
    with pytest.raises(ValueError, match="BGR"):
        detector.infer(frame)


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_confidence_is_rejected_before_model_loading(confidence):
    detector = YOLODetector(AppConfig())
    with pytest.raises(ValueError, match="Confidence"):
        detector.infer(np.zeros((8, 8, 3), dtype=np.uint8), confidence)


def test_runtime_mps_failure_falls_back_and_keeps_ids_distinct(monkeypatch):
    from sentinal.vision import detector as module
    detector = YOLODetector(AppConfig())
    class FakeModel:
        predictor = object()
        def to(self, device):
            assert device == "cpu"
    detector.model = FakeModel()
    detector.device = "mps"
    detector._maximum_track_id = 7
    calls = []
    def run(frame):
        calls.append(detector.device)
        if detector.device == "mps":
            raise RuntimeError("unit test: unsupported MPS operation")
        return object()
    monkeypatch.setattr(detector, "_run", run)
    monkeypatch.setattr(module, "synchronize", lambda device: None)
    monkeypatch.setattr(module, "detections_from_result", lambda *args: (
        Detection(0, "person", 0.8, (1, 1, 5, 5), 1),))
    output = detector.infer(np.zeros((8, 8, 3), dtype=np.uint8))
    assert calls == ["mps", "cpu"]
    assert detector.device == "cpu"
    assert detector.fallback_reason
    assert output[0].track_id > 7
    assert detector.last_inference_ms > 0


def test_cpu_model_failure_becomes_readable_error(monkeypatch):
    detector = YOLODetector(AppConfig())
    detector.model = object()
    def fail(frame):
        raise RuntimeError("unit test: model failure")
    monkeypatch.setattr(detector, "_run", fail)
    with pytest.raises(DetectorError, match="Detection failed"):
        detector.infer(np.zeros((8, 8, 3), dtype=np.uint8))


def test_model_without_target_classes_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "unit-fake.pt"
    path.write_bytes(b"unit stub, never real weights")
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(
        YOLO=lambda *args, **kwargs: SimpleNamespace(names={0: "person"})))
    detector = YOLODetector(AppConfig(model_path=str(path), device="cpu"))
    with pytest.raises(DetectorError, match="does not support"):
        detector.load()
    assert detector.model is None


def test_model_load_is_cached_and_tracker_reset_is_explicit(tmp_path, monkeypatch):
    path = tmp_path / "unit-fake.pt"
    path.write_bytes(b"unit stub, never real weights")
    loads, resets = [], []
    tracker = SimpleNamespace(reset=lambda: resets.append(True))
    model = SimpleNamespace(names={0: "person", 24: "backpack", 26: "handbag", 28: "suitcase"},
                            predictor=SimpleNamespace(trackers=[tracker], vid_path=["old-source"]))
    def make_model(*args, **kwargs):
        loads.append(True)
        return model
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=make_model))
    detector = YOLODetector(AppConfig(model_path=str(path), device="cpu"))
    assert detector.load() is detector
    assert detector.load() is detector
    assert len(loads) == 1
    detector.reset_tracking()
    assert resets == [True]
    assert model.predictor.vid_path == [None]
