"""Persistent model provenance, including migration of existing local stores."""
from dataclasses import replace
import sqlite3
from sentinal.storage.database import DetectionDatabase


def test_existing_database_migrates_and_records_model_name(tmp_path, packet):
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE sessions(session_id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL)')
    database = DetectionDatabase(path)
    try:
        database.record(replace(packet, model_name='yolov8n-oiv7.pt'))
        row = database.connection.execute('SELECT model_name FROM sessions WHERE session_id=?', (packet.session_id,)).fetchone()
        assert row == ('yolov8n-oiv7.pt',)
        assert database.count() == len(packet.detections)
    finally:
        database.close()
