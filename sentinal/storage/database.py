"""Bounded local metadata storage; this module never stores pixels or audio."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3


class DetectionDatabase:
    def __init__(self, path, retention_days=7, max_rows=100000):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.max_rows = max_rows
        self.connection = sqlite3.connect(str(self.path), timeout=1.0)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                frame_index INTEGER NOT NULL, source_time_s REAL NOT NULL,
                class_id INTEGER NOT NULL, category TEXT NOT NULL,
                confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                track_id INTEGER, x1 REAL NOT NULL, y1 REAL NOT NULL,
                x2 REAL NOT NULL, y2 REAL NOT NULL,
                fps REAL NOT NULL, inference_ms REAL NOT NULL, device TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS detection_time ON detections(timestamp);
            CREATE INDEX IF NOT EXISTS detection_session ON detections(session_id,track_id);
        ''')
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(sessions)")}
        if "model_name" not in columns:
            self.connection.execute("ALTER TABLE sessions ADD COLUMN model_name TEXT NOT NULL DEFAULT ''")
            self.connection.commit()
        self.prune()

    def record(self, packet):
        """Atomically persist one sampled frame; return detection rows written."""
        with self.connection:
            self.connection.execute('INSERT OR IGNORE INTO sessions(session_id,source,started_at,model_name) VALUES (?,?,?,?)',
                                    (packet.session_id, packet.source, packet.timestamp, getattr(packet, 'model_name', '')))
            self.connection.executemany(
                '''INSERT INTO detections(timestamp,session_id,frame_index,source_time_s,
                    class_id,category,confidence,track_id,x1,y1,x2,y2,fps,inference_ms,device)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                [(packet.timestamp, packet.session_id, packet.frame_index, packet.source_time_s,
                  d.class_id, d.label, d.confidence, d.track_id, *d.bbox,
                  packet.fps, packet.inference_ms, packet.device) for d in packet.detections])
        self.prune()
        return len(packet.detections)

    def prune(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat(timespec='milliseconds')
        with self.connection:
            self.connection.execute('DELETE FROM detections WHERE timestamp < ?', (cutoff,))
            self.connection.execute('''DELETE FROM detections WHERE id IN
                (SELECT id FROM detections ORDER BY id DESC LIMIT -1 OFFSET ?)''', (self.max_rows,))
            self.connection.execute('''DELETE FROM sessions WHERE session_id NOT IN
                (SELECT DISTINCT session_id FROM detections)''')

    def count(self):
        return self.connection.execute('SELECT COUNT(*) FROM detections').fetchone()[0]

    def close(self):
        self.connection.close()
