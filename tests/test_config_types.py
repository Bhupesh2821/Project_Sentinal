import json
import math

import pytest

from sentinal.config import AppConfig, ROOT, load_config
from sentinal.vision.types import BAG_CLASSES, Detection, count_objects, utc_now


def test_default_configuration_is_local_and_valid(tmp_path):
    config = load_config(tmp_path / "missing.json")
    assert config == AppConfig()
    assert config.weights == ROOT / "models/yolo11n.pt"
    assert not hasattr(config, "record_metadata")


def test_configuration_load_and_relative_weights(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"confidence": 0.5, "image_size": 320, "device": "cpu"}))
    config = load_config(path)
    assert (config.confidence, config.image_size, config.device) == (0.5, 320, "cpu")


@pytest.mark.parametrize("values", [
    {"confidence": 0.0}, {"confidence": 1.1}, {"confidence": math.nan},
    {"image_size": 123}, {"device": "cuda"}, {"camera_width": 32},
    {"sample_interval_s": 0.1}, {"sample_interval_s": math.nan}, {"retention_days": 0},
    {"max_detection_rows": 10}, {"model_path": "https://somewhere/model.bin"},
])
def test_configuration_rejects_invalid_values(values):
    with pytest.raises(ValueError):
        AppConfig(**values)


@pytest.mark.parametrize("field", [
    "image_size", "camera_width", "camera_height", "retention_days", "max_detection_rows",
])
@pytest.mark.parametrize("value", [100.5, True, "640", math.nan])
def test_configuration_rejects_noninteger_limits_and_dimensions(field, value):
    # A fractional row limit formerly reached SQLite OFFSET and disabled
    # recording with "datatype mismatch" instead of reporting bad settings.
    with pytest.raises(ValueError):
        AppConfig(**{field: value})


@pytest.mark.parametrize("field,value", [
    ("image_size", 640.0), ("camera_width", 640.0), ("camera_height", 480.0),
    ("retention_days", 7.0), ("max_detection_rows", 100.0),
])
def test_integer_settings_reject_float_values_even_when_numerically_equal(field, value):
    with pytest.raises(ValueError):
        AppConfig(**{field: value})


@pytest.mark.parametrize("field", ["confidence", "sample_interval_s"])
@pytest.mark.parametrize("value", [True, "0.5", None, math.nan, math.inf])
def test_configuration_rejects_nonnumeric_or_nonfinite_measurements(field, value):
    with pytest.raises(ValueError):
        AppConfig(**{field: value})


@pytest.mark.parametrize("values", [
    {"model_path": None}, {"model_path": True}, {"model_path": 123},
    {"device": None}, {"device": []}, {"device": True},
])
def test_configuration_reports_wrong_path_and_device_types(values):
    with pytest.raises(ValueError):
        AppConfig(**values)


def test_whole_metadata_row_limit_remains_usable_by_sqlite(tmp_path):
    from sentinal.storage.database import DetectionDatabase
    config = load_config(tmp_path / "absent.json")
    with pytest.raises(ValueError):
        AppConfig(max_detection_rows=100.5)
    database = DetectionDatabase(tmp_path / "metadata.sqlite3", config.retention_days,
                                 config.max_detection_rows)
    try:
        assert database.count() == 0
    finally:
        database.close()
    assert AppConfig(sample_interval_s=2).sample_interval_s == 2


@pytest.mark.parametrize("content", ['{"enable_logging": true}', '[]', '{broken'])
def test_configuration_rejects_unknown_or_corrupt_settings(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        load_config(path)


@pytest.mark.parametrize("changes", [
    {"class_id": -1}, {"label": ""}, {"confidence": -0.1},
    {"confidence": math.nan}, {"confidence": math.inf},
    {"bbox": (0, 0, 0, 2)}, {"bbox": (-1, 0, 2, 2)},
    {"bbox": (0, 0, 2, math.inf)}, {"bbox": (0, 0, 2)}, {"track_id": -1},
])
def test_detection_validates_untrusted_coordinates(changes):
    values = dict(class_id=0, label="person", confidence=0.8,
                  bbox=(0, 0, 10, 20), track_id=None)
    values.update(changes)
    with pytest.raises(ValueError):
        Detection(**values)


def test_counts_distinguish_detection_tracking_people_and_bags(packet):
    objects = packet.detections + (
        Detection(26, "handbag", 0.7, (1, 1, 2, 2)),
        Detection(28, "suitcase", 0.6, (2, 2, 3, 3)),
        Detection(56, "chair", 0.9, (3, 3, 4, 4), 10),
    )
    assert BAG_CLASSES == {"backpack", "handbag", "suitcase"}
    assert count_objects(objects) == {"people": 1, "bags": 3, "tracked": 3, "detections": 5}
    assert count_objects(()) == {"people": 0, "bags": 0, "tracked": 0, "detections": 0}


def test_timestamp_is_timezone_aware():
    from datetime import datetime
    assert datetime.fromisoformat(utc_now()).utcoffset() is not None
