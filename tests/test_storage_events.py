from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from types import SimpleNamespace

import pytest

from sentinal.config import AppConfig
from sentinal.core.event_manager import EventManager, format_event
from sentinal.storage.database import DetectionDatabase


def test_database_persists_full_metadata_without_pixels_or_audio(tmp_path, packet):
    path = tmp_path / "nested" / "detections.sqlite3"
    db = DetectionDatabase(path)
    try:
        assert db.record(packet) == 2
        assert db.count() == 2
        row = db.connection.execute("SELECT category,confidence,track_id,x1,y1,x2,y2,device FROM detections ORDER BY id").fetchone()
        assert row == ("person", 0.91, 7, 1, 2, 25, 45, "cpu")
        columns = {row[1] for row in db.connection.execute("PRAGMA table_info(detections)")}
        assert not columns & {"frame", "image", "audio", "video", "face"}
    finally:
        db.close()
    reopened = DetectionDatabase(path)
    assert reopened.count() == 2
    reopened.close()


def test_session_keys_prevent_cross_run_tracking_collisions(tmp_path, packet):
    db = DetectionDatabase(tmp_path / "detections.sqlite3")
    try:
        db.record(packet)
        db.record(replace(packet, session_id="unit-session-b"))
        rows = db.connection.execute("SELECT DISTINCT session_id,track_id FROM detections WHERE track_id=7").fetchall()
        assert set(rows) == {("unit-session-a", 7), ("unit-session-b", 7)}
        assert db.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
    finally:
        db.close()


def test_row_cap_and_retention_prune_metadata(tmp_path, packet):
    db = DetectionDatabase(tmp_path / "detections.sqlite3", retention_days=7, max_rows=3)
    try:
        db.record(packet)
        db.record(replace(packet, frame_index=2))
        assert db.count() == 3
        ancient = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        db.connection.execute("UPDATE detections SET timestamp=?", (ancient,))
        db.connection.commit()
        db.prune()
        assert db.count() == 0
        assert db.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    finally:
        db.close()


def test_empty_snapshot_does_not_create_detection_rows(tmp_path, packet):
    db = DetectionDatabase(tmp_path / "detections.sqlite3")
    try:
        assert db.record(replace(packet, detections=())) == 0
        assert db.count() == 0
    finally:
        db.close()


def test_metadata_formatter_has_stable_global_track_key_and_json_fields(packet):
    event = format_event(packet, packet.detections[0])
    assert event["track_key"] == "unit-session-a:7"
    assert event["bbox"] == [1, 2, 25, 45]
    assert event["category"] == "person"
    assert event["timestamp"] == packet.timestamp
    assert json.loads(json.dumps(event)) == event
    untracked = replace(packet.detections[0], track_id=None)
    assert format_event(packet, untracked)["track_key"] is None


def test_event_recording_is_off_by_default(tmp_path, packet):
    path = tmp_path / "private.sqlite3"
    manager = EventManager(AppConfig(), path)
    assert manager.process(packet) is None
    assert manager.database is None
    assert not path.exists()


def test_event_sampling_session_reset_and_opt_out(tmp_path, packet):
    current = [100.0]
    manager = EventManager(AppConfig(sample_interval_s=2), tmp_path / "events.sqlite3",
                           clock=lambda: current[0])
    try:
        assert manager.process(packet, enabled=True) is None
        assert manager.database.count() == 2
        current[0] = 101.0
        manager.process(replace(packet, frame_index=2), enabled=True)
        assert manager.database.count() == 2
        current[0] = 102.1
        manager.process(replace(packet, frame_index=3), enabled=True)
        assert manager.database.count() == 4
        # A new independent session is sampled immediately even within the cadence.
        manager.process(replace(packet, session_id="second-session"), enabled=True)
        assert manager.database.count() == 6
        manager.process(packet, enabled=False)
        assert manager.database is None
        assert manager.last_sample is None
    finally:
        manager.close()


def test_database_open_failure_does_not_abort_monitoring(tmp_path, packet, monkeypatch):
    from sentinal.core import event_manager
    def fail_database(*args, **kwargs):
        raise sqlite3.OperationalError("unit test: read-only database")
    monkeypatch.setattr(event_manager, "DetectionDatabase", fail_database)
    manager = EventManager(AppConfig(), tmp_path / "events.sqlite3")
    error = manager.process(packet, enabled=True)
    assert "Metadata could not be saved" in error
    assert "monitoring can continue" in error
    assert manager.database is None


def test_database_write_failure_closes_failed_connection(tmp_path, packet, monkeypatch):
    from sentinal.core import event_manager
    class BrokenDatabase:
        closed = False
        def __init__(self, *args):
            pass
        def record(self, packet):
            raise sqlite3.OperationalError("unit test: disk full")
        def close(self):
            type(self).closed = True
    monkeypatch.setattr(event_manager, "DetectionDatabase", BrokenDatabase)
    manager = EventManager(AppConfig(), tmp_path / "events.sqlite3")
    assert manager.process(packet, enabled=True)
    assert manager.database is None
    assert BrokenDatabase.closed


def test_record_after_closed_database_fails_explicitly(tmp_path, packet):
    db = DetectionDatabase(tmp_path / "detections.sqlite3")
    db.close()
    with pytest.raises(sqlite3.ProgrammingError):
        db.record(packet)


def test_partial_failed_snapshot_is_rolled_back_atomically(tmp_path, packet):
    db = DetectionDatabase(tmp_path / "detections.sqlite3")
    # Bypass Detection validation to exercise SQLite's independent constraint.
    invalid = SimpleNamespace(class_id=0, label="person", confidence=2.0,
                              track_id=99, bbox=(1, 2, 20, 30))
    malformed_packet = replace(packet, detections=(packet.detections[0], invalid))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            db.record(malformed_packet)
        assert db.count() == 0
        assert db.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    finally:
        db.close()
