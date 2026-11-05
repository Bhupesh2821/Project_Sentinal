"""Bounded owner-local outbound metadata spool; never stores video frames."""
from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
import time
from sentinal.config import ROOT


def local_file(path):
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Connected metadata and credentials must stay inside the project')
    return path


def private_parent(path):
    path = local_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.resolve() != ROOT.resolve():
        path.parent.chmod(0o700)
    return path


@dataclass(frozen=True)
class PendingEvent:
    event_id: str
    payload: bytes
    attempts: int
    created_at: float


class OutboxDestinationError(ValueError):
    pass


class Outbox:
    """Single-thread owner. Failed entries remain bounded and diagnosable.

    Reject overflow instead of discarding an unsent incident silently. Successfully
    accepted events are removed; retries use the same body and event identifier.
    """
    def __init__(self, path, max_events=500, max_age_s=7 * 86400, *, destination=None):
        if type(max_events) is not int or not 1 <= max_events <= 10000:
            raise ValueError('Outbound event limit must be 1 to 10000')
        if type(max_age_s) not in (int, float) or not 60 <= max_age_s <= 365 * 86400:
            raise ValueError('Outbound retention must be 60 seconds to 365 days')
        self.path = private_parent(path)
        self.max_events = max_events
        self.max_age_s = max_age_s
        self.connection = sqlite3.connect(str(self.path), timeout=3)
        self.path.chmod(0o600)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA secure_delete=ON')
        self.connection.execute('''CREATE TABLE IF NOT EXISTS outbound_events (
            event_id TEXT PRIMARY KEY, payload BLOB NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'queued',
            next_attempt REAL NOT NULL, created_at REAL NOT NULL,
            last_error TEXT NOT NULL DEFAULT '')''')
        self.connection.execute('CREATE TABLE IF NOT EXISTS outbound_binding (id INTEGER PRIMARY KEY CHECK(id=1), destination TEXT NOT NULL)')
        if destination is not None:
            previous=self.connection.execute('SELECT destination FROM outbound_binding WHERE id=1').fetchone()
            if previous is not None and previous[0]!=destination:
                self.connection.close()
                raise OutboxDestinationError('This outbox belongs to another device connection. Pending metadata was retained and not transmitted.')
            if previous is None:
                if self.connection.execute('SELECT COUNT(*) FROM outbound_events').fetchone()[0]:
                    self.connection.close()
                    raise OutboxDestinationError('Unbound pending metadata requires explicit migration; it was retained and not transmitted.')
                self.connection.execute('INSERT INTO outbound_binding(id,destination) VALUES(1,?)',(destination,))
        self.connection.commit()

    def expire(self, now=None):
        now = time.time() if now is None else now
        with self.connection:
            cursor = self.connection.execute('DELETE FROM outbound_events WHERE created_at<?',
                (now - self.max_age_s,))
        return cursor.rowcount

    def enqueue(self, event, now=None):
        from .protocol import canonical_json, validate_event
        validate_event(event)
        body = canonical_json(event)
        if len(body) > 128 * 1024:
            raise ValueError('Outbound event exceeds its body limit')
        ident = event['event_id']
        now = time.time() if now is None else now
        with self.connection:
            previous = self.connection.execute('SELECT payload FROM outbound_events WHERE event_id=?', (ident,)).fetchone()
            if previous:
                if bytes(previous[0]) != body:
                    raise ValueError('An event ID cannot be reused with changed metadata')
                return False
            count = self.connection.execute('SELECT COUNT(*) FROM outbound_events').fetchone()[0]
            if count >= self.max_events:
                raise OverflowError('Outbound metadata spool is full; inspect connection diagnostics')
            self.connection.execute('INSERT INTO outbound_events(event_id,payload,next_attempt,created_at) VALUES(?,?,?,?)',
                (ident, body, now, now))
        return True

    def ready(self, now=None):
        now = time.time() if now is None else now
        row = self.connection.execute('''SELECT event_id,payload,attempts,created_at FROM outbound_events
            WHERE state='queued' AND next_attempt<=? ORDER BY next_attempt,created_at,event_id LIMIT 1''', (now,)).fetchone()
        return PendingEvent(row[0], bytes(row[1]), row[2], row[3]) if row else None

    def accepted(self, ident):
        with self.connection:
            self.connection.execute('DELETE FROM outbound_events WHERE event_id=?', (ident,))

    def retry(self, ident, delay_s, error='Delivery will be retried', now=None):
        now = time.time() if now is None else now
        with self.connection:
            self.connection.execute('''UPDATE outbound_events SET attempts=attempts+1,next_attempt=?,last_error=? WHERE event_id=?''',
                (now + max(0, min(3600, delay_s)), error[:200], ident))

    def failed(self, ident, error='Backend rejected event'):
        with self.connection:
            self.connection.execute("UPDATE outbound_events SET state='failed',attempts=attempts+1,last_error=? WHERE event_id=?", (error[:200], ident))

    def counts(self):
        values = dict(self.connection.execute('SELECT state,COUNT(*) FROM outbound_events GROUP BY state'))
        return {'queued': values.get('queued', 0), 'failed': values.get('failed', 0)}

    def close(self):
        self.connection.close()
