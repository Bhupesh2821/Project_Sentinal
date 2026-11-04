"""Adapt supported Ultralytics Boxes results into validated source-pixel data."""
import logging
import math

from .types import Detection
from .object_catalog import canonical_label, label_allowed

log = logging.getLogger(__name__)


def _list(value):
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    return value.tolist() if hasattr(value, "tolist") else list(value)


def detections_from_result(result, frame_shape, confidence=0.0, track_ids=None):
    """Keep valid boxes, clip to the original frame and retain optional track IDs.

    Ultralytics already transforms its letterboxed inference coordinates back to
    original input pixels. Scaling these a second time would misplace boxes.
    Invalid individual model rows are discarded and logged, never shown.
    """
    if len(frame_shape) < 2 or min(frame_shape[:2]) <= 0:
        raise ValueError("A positive frame height and width are required")
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Confidence must be between zero and one")
    boxes = result.boxes
    if boxes is None:
        return ()
    xyxy, scores, classes = _list(boxes.xyxy), _list(boxes.conf), _list(boxes.cls)
    if not xyxy:
        return ()
    ids = [track_ids.get(i) for i in range(len(xyxy))] if track_ids is not None else (_list(boxes.id) if boxes.id is not None else [None] * len(xyxy))
    if not len(xyxy) == len(scores) == len(classes) == len(ids):
        raise ValueError("Inconsistent detector result array lengths")
    height, width = frame_shape[:2]
    names = result.names
    detections = []
    for coords, score, class_value, track_value in zip(xyxy, scores, classes, ids):
        try:
            score = float(score)
            if score < confidence:
                continue
            if len(coords) != 4 or not all(math.isfinite(float(v)) for v in coords):
                raise ValueError("non-finite or incomplete coordinates")
            if not math.isfinite(float(class_value)) or int(class_value) != class_value:
                raise ValueError("invalid class ID")
            class_id = int(class_value)
            raw_label = names[class_id]
            if not label_allowed(raw_label):
                continue
            label = canonical_label(raw_label)
            x1, y1, x2, y2 = map(float, coords)
            clipped = (max(0.0, min(float(width), x1)), max(0.0, min(float(height), y1)),
                       max(0.0, min(float(width), x2)), max(0.0, min(float(height), y2)))
            if track_value is not None:
                if not math.isfinite(float(track_value)) or int(track_value) != track_value:
                    raise ValueError("invalid track ID")
                track_value = int(track_value)
            detections.append(Detection(class_id, str(label), score, clipped, track_value))
        except (ValueError, TypeError, KeyError, IndexError, OverflowError):
            log.warning("Discarded invalid detection row", exc_info=True)
    return tuple(detections)


def reset_model_trackers(model):
    """Reset ByteTrack's documented tracker instance state between sources."""
    predictor = getattr(model, "predictor", None)
    for tracker in getattr(predictor, "trackers", ()):
        tracker.reset()
    if predictor is not None and hasattr(predictor, "vid_path"):
        predictor.vid_path = [None] * len(predictor.vid_path)
