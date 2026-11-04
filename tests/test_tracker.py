from types import SimpleNamespace

import numpy as np
import pytest

from sentinal.vision.tracker import detections_from_result


def result(boxes, confidence, classes, ids=None):
    class FakeBoxes(SimpleNamespace):
        def __len__(self):
            return len(self.xyxy)
    return SimpleNamespace(
        boxes=FakeBoxes(xyxy=np.array(boxes, dtype=float).reshape(-1, 4),
                              conf=np.array(confidence, dtype=float),
                              cls=np.array(classes, dtype=float),
                              id=None if ids is None else np.array(ids, dtype=float)),
        names={0: "person", 24: "backpack", 26: "handbag", 28: "suitcase", 56: "chair"},
    )


def test_tracking_conversion_preserves_class_confidence_bbox_and_ids():
    output = detections_from_result(result([[2, 3, 20, 40], [25, 5, 50, 45]],
                                           [0.9, 0.8], [0, 24], [7, 8]), (48, 64, 3))
    assert len(output) == 2
    assert output[0].label == "person"
    assert output[0].bbox == (2, 3, 20, 40)
    assert output[0].confidence == pytest.approx(0.9)
    assert output[0].track_id == 7
    assert output[1].label == "backpack"
    assert output[1].track_id == 8


def test_unassigned_detection_ids_are_none():
    output = detections_from_result(result([[2, 3, 20, 40]], [0.9], [0]), (48, 64, 3))
    assert output[0].track_id is None


def test_empty_frames_and_empty_results_do_not_create_objects():
    assert detections_from_result(SimpleNamespace(boxes=None, names={}), (48, 64, 3)) == ()
    assert detections_from_result(result([], [], []), (48, 64, 3)) == ()


def test_confidence_filter_is_applied_after_tracker_conversion():
    output = detections_from_result(result([[1, 1, 5, 5], [5, 5, 10, 10]],
                                           [0.2, 0.8], [0, 24], [1, 2]),
                                    (48, 64, 3), confidence=0.5)
    assert len(output) == 1
    assert output[0].label == "backpack"


def test_coordinates_are_clipped_to_original_frame_and_invalid_boxes_dropped():
    output = detections_from_result(result([[-5, -4, 80, 90], [10, 10, 10, 20]],
                                           [0.9, 0.8], [0, 24], [1, 2]), (48, 64, 3))
    assert len(output) == 1
    assert output[0].bbox == (0, 0, 64, 48)


def test_invalid_result_rows_are_dropped_without_poisoning_valid_rows():
    output = detections_from_result(result([[1, 1, 5, 5], [1, 1, 5, 5], [1, 1, 5, 5]],
                                           [0.9, float("nan"), 0.8], [0, 24, 999], [1, 2, 3]),
                                    (48, 64, 3))
    assert len(output) == 1
    assert output[0].track_id == 1


def test_inconsistent_detector_arrays_are_reported():
    with pytest.raises(ValueError, match="array lengths"):
        detections_from_result(result([[1, 1, 5, 5]], [], [0], [1]), (48, 64, 3))


@pytest.mark.parametrize("confidence", [-1, 2, float("nan")])
def test_invalid_normalization_confidence_rejected(confidence):
    with pytest.raises(ValueError):
        detections_from_result(result([], [], []), (48, 64, 3), confidence)
