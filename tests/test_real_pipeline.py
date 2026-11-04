"""Opt-in integration smoke test. No mocks and no synthetic motion footage.

Run with SENTINAL_TEST_VIDEO=/absolute/path/to/real-footage.mp4 and local
weights in models/yolo11n.pt (or SENTINAL_TEST_WEIGHTS). Test output that says
SKIPPED is not evidence that a model, camera, or tracking actually worked.
"""
import os
from pathlib import Path

import pytest

from sentinal.config import AppConfig, ROOT


def test_real_video_inference_and_tracking():
    video = os.environ.get("SENTINAL_TEST_VIDEO")
    if not video:
        pytest.skip("Set SENTINAL_TEST_VIDEO to real recorded footage to run real inference")
    path = Path(video)
    assert path.is_file(), "The explicitly configured real video must exist"
    weights = Path(os.environ.get("SENTINAL_TEST_WEIGHTS", ROOT / "models/yolo11n.pt"))
    assert weights.is_file(), "Install the real local model before running this smoke test"
    from sentinal.vision.pipeline import VisionPipeline
    from sentinal.vision.video_source import SourceSpec
    pipeline = VisionPipeline(AppConfig(model_path=str(weights), device="cpu", image_size=320))
    observed = []
    identities = set()
    try:
        pipeline.start(SourceSpec("file", str(path)))
        for _ in range(30):
            packet = pipeline.step()
            if packet is None:
                break
            observed.append(packet)
            identities.update(d.track_id for d in packet.detections if d.track_id is not None)
    finally:
        pipeline.stop()
    assert len(observed) >= 2, "Need multiple real frames for tracking smoke evidence"
    assert any(packet.detections for packet in observed), "Suitable footage must yield real detections"
    assert identities, "Suitable moving-object footage must produce at least one assigned tracking ID"
    assert all(packet.inference_ms > 0 for packet in observed)
    assert all(packet.frame.shape[0] > 0 for packet in observed)
    assert len({packet.session_id for packet in observed}) == 1
    assert observed[-1].frame_index > observed[0].frame_index
