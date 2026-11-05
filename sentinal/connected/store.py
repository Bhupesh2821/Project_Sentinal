"""Owner-local SQLite authority for connected accounts, devices and incidents."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from uuid import uuid4
from sentinal.core.incidents import TRANSITIONS
from .protocol import canonical_json, device_identifier, secret_key, text, validate_event

ROLES = {'admin', 'operator', 'viewer'}
SESSION_SECONDS = 8 * 60 * 60


class StoreError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise StoreError('Password must contain 12–1024 characters')
    salt = secrets.token_bytes(16) if salt is None else salt
    # One OWASP-listed scrypt minimum: 16 MiB with p=5. No optional dependency.
    derived = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384, r=8, p=5)
    return 'scrypt$16384$8$5$' + salt.hex() + '$' + derived.hex()


def password_matches(password, stored):
    try:
        if not isinstance(password, str) or not 12 <= len(password) <= 1024:
            return False
        if stored.startswith('scrypt$'):
            algorithm, n, r, p, salt, expected = stored.split('$')
            if (algorithm, n, r, p) != ('scrypt', '16384', '8', '5'):
                return False
            lanes = 5
        else:
            # Temporary initial prototype accounts are upgraded after login.
            salt, expected = stored.split(':')
            lanes = 1
        derived = hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt), n=16384, r=8, p=lanes).hex()
        return hmac.compare_digest(derived, expected)
    except (TypeError, ValueError):
        return False


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.path.chmod(0o600)
        self._dummy_password = password_hash(secrets.token_urlsafe(32))
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users(
          id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
          role TEXT NOT NULL, organization TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS devices(
          device_id TEXT PRIMARY KEY, name TEXT NOT NULL, organization TEXT NOT NULL,
          signing_key BLOB NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, last_seen TEXT,
          received_at REAL, health TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS nonces(device_id TEXT NOT NULL,nonce TEXT NOT NULL,received REAL NOT NULL,PRIMARY KEY(device_id,nonce));
        CREATE TABLE IF NOT EXISTS receipts(device_id TEXT NOT NULL,event_id TEXT NOT NULL,body_hash TEXT NOT NULL,received_at TEXT NOT NULL,PRIMARY KEY(device_id,event_id));
        CREATE TABLE IF NOT EXISTS incidents(
          organization TEXT NOT NULL,incident_id TEXT NOT NULL,device_id TEXT NOT NULL,
          source_id TEXT NOT NULL,category TEXT NOT NULL,status TEXT NOT NULL,severity INTEGER NOT NULL,
          confidence REAL NOT NULL,last_seen TEXT NOT NULL,payload TEXT NOT NULL,
          version INTEGER NOT NULL,received_at TEXT NOT NULL,reviewed_at TEXT,reviewed_by TEXT,review_note TEXT,
          PRIMARY KEY(organization,incident_id));
        CREATE TABLE IF NOT EXISTS cameras(
          organization TEXT NOT NULL,camera_id TEXT NOT NULL,device_id TEXT NOT NULL,
          name TEXT NOT NULL,status TEXT NOT NULL,last_frame_at TEXT,updated_at TEXT NOT NULL,
          PRIMARY KEY(organization,camera_id));
        CREATE TABLE IF NOT EXISTS models(
          organization TEXT NOT NULL,device_id TEXT NOT NULL,model_id TEXT NOT NULL,
          version TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL,
          PRIMARY KEY(organization,device_id,model_id,version));
        CREATE TABLE IF NOT EXISTS audit(
          id INTEGER PRIMARY KEY AUTOINCREMENT,organization TEXT NOT NULL,incident_id TEXT,
          actor TEXT NOT NULL,action TEXT NOT NULL,timestamp TEXT NOT NULL,details TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(organization TEXT PRIMARY KEY,retention_days INTEGER NOT NULL DEFAULT 7);
        CREATE TABLE IF NOT EXISTS attempts(bucket TEXT PRIMARY KEY,count INTEGER NOT NULL,reset_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS incident_scope ON incidents(organization,last_seen);
        CREATE INDEX IF NOT EXISTS audit_scope ON audit(organization,id);
        ''')
        self.db.commit()

    @contextmanager
    def transaction(self):
        with self.lock:
            try:
                self.db.execute('BEGIN IMMEDIATE')
                yield
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def close(self):
        with self.lock:
            self.db.close()

    def _audit(self, organization, actor, action, incident_id=None, details=None):
        self.db.execute('INSERT INTO audit(organization,incident_id,actor,action,timestamp,details) VALUES(?,?,?,?,?,?)',
                        (organization, incident_id, actor, action, utc_now(), json.dumps(details or {}, separators=(',', ':'))))

    def create_user(self, username, password, role='admin', organization='default'):
        text(username, 'Username', 80)
        if any(c.isspace() for c in username) or role not in ROLES:
            raise StoreError('Invalid username or role')
        device_identifier(organization)
        encoded = password_hash(password)
        ident = str(uuid4())
        with self.transaction():
            try:
                self.db.execute('INSERT INTO users(id,username,password,role,organization,created_at) VALUES(?,?,?,?,?,?)',
                                (ident, username.casefold(), encoded, role, organization, utc_now()))
            except sqlite3.IntegrityError:
                raise StoreError('Username already exists', 409) from None
            self.db.execute('INSERT OR IGNORE INTO settings(organization) VALUES(?)', (organization,))
            self._audit(organization, ident, 'user_created', details={'username': username.casefold(), 'role': role})
        return {'id': ident, 'username': username.casefold(), 'role': role, 'organization': organization}

    def users(self, organization):
        with self.lock:
            return [dict(row) for row in self.db.execute('SELECT id,username,role,enabled,created_at FROM users WHERE organization=? ORDER BY username', (organization,))]

    def register_device(self, device_id, name, secret, organization='default'):
        device_identifier(device_id)
        device_identifier(organization)
        text(name, 'Device name', 128)
        key = secret_key(secret)
        with self.transaction():
            try:
                self.db.execute('INSERT INTO devices(device_id,name,organization,signing_key) VALUES(?,?,?,?)', (device_id, name, organization, key))
            except sqlite3.IntegrityError:
                raise StoreError('Device already exists; rotate it explicitly instead of replacing credentials', 409) from None
            self._audit(organization, 'local provisioning', 'device_registered', details={'device_id': device_id, 'name': name})
        return {'device_id': device_id, 'name': name, 'organization': organization}

    def device(self, device_id):
        with self.lock:
            row = self.db.execute('SELECT * FROM devices WHERE device_id=? AND enabled=1', (device_id,)).fetchone()
            return dict(row) if row else None

    def accept_nonce(self, device_id, nonce, now=None):
        now = time.time() if now is None else now
        with self.transaction():
            self.db.execute('DELETE FROM nonces WHERE rowid IN(SELECT rowid FROM nonces WHERE received<? LIMIT 1000)', (now - 180,))
            if self.db.execute('SELECT COUNT(*) FROM nonces').fetchone()[0] >= 60000:
                raise StoreError('Replay protection is busy; retry later', 429)
            try:
                self.db.execute('INSERT INTO nonces VALUES(?,?,?)', (device_id, nonce, now))
            except sqlite3.IntegrityError:
                raise StoreError('Signed request was already used', 409) from None

    def rate_limit(self, bucket, maximum=120, window=60):
        now = time.time()
        with self.transaction():
            self.db.execute('DELETE FROM attempts WHERE bucket IN(SELECT bucket FROM attempts WHERE reset_at<? LIMIT 1000)', (now,))
            row = self.db.execute('SELECT * FROM attempts WHERE bucket=?', (bucket,)).fetchone()
            if row and row['reset_at'] > now:
                if row['count'] >= maximum:
                    raise StoreError('Too many requests; retry later', 429)
                self.db.execute('UPDATE attempts SET count=count+1 WHERE bucket=?', (bucket,))
            else:
                if self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] >= 10000:
                    raise StoreError('Request limiter is busy; retry later', 429)
                self.db.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)', (bucket, 1, now + window))

    def login(self, username, password, remote):
        if not isinstance(username, str) or len(username) > 80:
            raise StoreError('Invalid username or password', 401)
        self.rate_limit('login-ip:' + remote, 20, 900)
        self.rate_limit('login-user:' + digest(username.casefold()), 8, 900)
        with self.lock:
            row = self.db.execute('SELECT * FROM users WHERE username=?', (username.casefold(),)).fetchone()
        valid = password_matches(password, row['password'] if row else self._dummy_password)
        if not row or not row['enabled'] or not valid:
            raise StoreError('Invalid username or password', 401)
        token = secrets.token_urlsafe(32)
        with self.transaction():
            if not row['password'].startswith('scrypt$16384$8$5$'):
                self.db.execute('UPDATE users SET password=? WHERE id=?', (password_hash(password), row['id']))
            self.db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            self.db.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(token), row['id'], time.time() + SESSION_SECONDS))
            self._audit(row['organization'], row['id'], 'login')
        return token, {name: row[name] for name in ('id', 'username', 'role', 'organization')}

    def session(self, token):
        if not isinstance(token, str) or len(token) > 128:
            return None
        with self.lock:
            row = self.db.execute('SELECT u.id,u.username,u.role,u.organization FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token_hash=? AND s.expires>? AND u.enabled=1', (digest(token), time.time())).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        with self.transaction():
            self.db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token),))

    def ingest(self, event, body_hash, device):
        validate_event(event)
        if event['device_id'] != device['device_id']:
            raise StoreError('Device identity mismatch', 401)
        organization = device['organization']
        now = utc_now()
        result = {'ok': True, 'event_id': event['event_id'], 'duplicate': False}
        with self.transaction():
            authorized = self.db.execute('SELECT organization FROM devices WHERE device_id=? AND enabled=1', (device['device_id'],)).fetchone()
            if not authorized or authorized['organization'] != organization:
                raise StoreError('Device authorization was revoked', 401)
            old = self.db.execute('SELECT body_hash FROM receipts WHERE device_id=? AND event_id=?', (device['device_id'], event['event_id'])).fetchone()
            if old:
                if not hmac.compare_digest(old['body_hash'], body_hash):
                    raise StoreError('Event ID already identifies different content', 409)
                return {**result, 'duplicate': True}
            self._expire(organization)
            if event['kind'] == 'incident':
                raw = dict(event['incident'])
                ident = raw['incident_id']
                camera = self.db.execute('SELECT device_id FROM cameras WHERE organization=? AND camera_id=?', (organization, raw['source_id'])).fetchone()
                if camera and camera['device_id'] != device['device_id']:
                    raise StoreError('Camera belongs to another device', 403)
                previous = self.db.execute('SELECT * FROM incidents WHERE organization=? AND incident_id=?', (organization, ident)).fetchone()
                if previous and previous['device_id'] != device['device_id']:
                    raise StoreError('Incident ID belongs to another device', 409)
                # A delayed source update never changes an operator's decision.
                reviewed = previous and previous['status'] in {'ACKNOWLEDGED', 'VERIFIED', 'DISMISSED', 'CLOSED'}
                stage = {'OBSERVED': 0, 'CANDIDATE': 1, 'ALERTED': 2}
                fresh = not previous or (datetime.fromisoformat(raw['last_seen']) >= datetime.fromisoformat(previous['last_seen']) and stage.get(raw['status'], -1) >= stage.get(previous['status'], -1))
                if not reviewed and fresh:
                    version = previous['version'] + 1 if previous else 1
                    self.db.execute('''INSERT INTO incidents(organization,incident_id,device_id,source_id,category,status,severity,confidence,last_seen,payload,version,received_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization,incident_id) DO UPDATE SET status=excluded.status,severity=excluded.severity,
                      confidence=excluded.confidence,last_seen=excluded.last_seen,payload=excluded.payload,version=excluded.version,received_at=excluded.received_at''',
                      (organization, ident, device['device_id'], raw['source_id'], raw['category'], raw['status'], raw['severity'], raw['confidence'], datetime.fromisoformat(raw['last_seen']).astimezone(timezone.utc).isoformat(), canonical_json(raw).decode(), version, now))
                    self._audit(organization, device['device_id'], 'edge_incident_' + raw['status'].lower(), ident, {'event_id': event['event_id'], 'version': version})
                result['incident_id'] = ident
            else:
                current = self.db.execute('SELECT last_seen FROM devices WHERE device_id=?', (device['device_id'],)).fetchone()
                if current and current['last_seen'] and datetime.fromisoformat(event['occurred_at']) < datetime.fromisoformat(current['last_seen']):
                    self.db.execute('INSERT INTO receipts VALUES(?,?,?,?)', (device['device_id'], event['event_id'], body_hash, now))
                    return result
                self.db.execute('UPDATE devices SET health=?,last_seen=?,received_at=? WHERE device_id=?',
                                (canonical_json(event['health']).decode(), event['occurred_at'], time.time(), device['device_id']))
                self.db.execute('UPDATE cameras SET status=? WHERE organization=? AND device_id=?', ('offline', organization, device['device_id']))
                for camera in event['cameras']:
                    previous = self.db.execute('SELECT device_id FROM cameras WHERE organization=? AND camera_id=?', (organization, camera['camera_id'])).fetchone()
                    if previous and previous['device_id'] != device['device_id']:
                        raise StoreError('Camera ID belongs to another device', 409)
                    self.db.execute('''INSERT INTO cameras VALUES(?,?,?,?,?,?,?) ON CONFLICT(organization,camera_id) DO UPDATE SET
                      name=excluded.name,status=excluded.status,last_frame_at=excluded.last_frame_at,updated_at=excluded.updated_at''',
                      (organization, camera['camera_id'], device['device_id'], camera['name'], camera['status'], camera.get('last_frame_at'), now))
                self.db.execute('DELETE FROM models WHERE organization=? AND device_id=?', (organization, device['device_id']))
                for model in event['models']:
                    self.db.execute('INSERT INTO models VALUES(?,?,?,?,?,?)',
                                    (organization, device['device_id'], model['model_id'], model['version'], canonical_json(model).decode(), now))
            self.db.execute('INSERT INTO receipts VALUES(?,?,?,?)', (device['device_id'], event['event_id'], body_hash, now))
            self.db.execute('DELETE FROM receipts WHERE rowid IN(SELECT rowid FROM receipts ORDER BY rowid DESC LIMIT -1 OFFSET 100000)')
        return result

    def _expire(self, organization):
        setting = self.db.execute('SELECT retention_days FROM settings WHERE organization=?', (organization,)).fetchone()
        days = setting[0] if setting else 7
        cutoff = datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).isoformat()
        self.db.execute('DELETE FROM incidents WHERE organization=? AND received_at<?', (organization, cutoff))
        self.db.execute('DELETE FROM incidents WHERE organization=? AND incident_id IN(SELECT incident_id FROM incidents WHERE organization=? ORDER BY received_at DESC LIMIT -1 OFFSET 10000)', (organization, organization))
        self.db.execute('DELETE FROM audit WHERE organization=? AND id IN(SELECT id FROM audit WHERE organization=? ORDER BY id DESC LIMIT -1 OFFSET 20000)', (organization, organization))

    def _incident(self, row):
        if not row:
            return None
        value = json.loads(row['payload'])
        value.update({key: row[key] for key in ('device_id', 'status', 'version', 'received_at', 'reviewed_at', 'reviewed_by', 'review_note')})
        value['evidence_available'] = False
        return value

    def incident(self, organization, ident):
        with self.lock:
            return self._incident(self.db.execute('SELECT * FROM incidents WHERE organization=? AND incident_id=?', (organization, ident)).fetchone())

    def incidents(self, organization, filters=None):
        filters = filters or {}
        if set(filters) - {'status', 'category', 'severity', 'search', 'limit'}:
            raise StoreError('Unsupported incident filter')
        limit = int(filters.get('limit', 200))
        if not 1 <= limit <= 200:
            raise StoreError('Limit must be 1–200')
        where, values = ['organization=?'], [organization]
        for key in ('status', 'category', 'severity'):
            if filters.get(key):
                where.append(key + '=?')
                values.append(filters[key])
        if filters.get('search'):
            search = str(filters['search'])
            if len(search) > 128:
                raise StoreError('Search is too long')
            where.append('(incident_id LIKE ? OR source_id LIKE ? OR category LIKE ?)')
            values.extend(['%' + search + '%'] * 3)
        with self.lock:
            return [self._incident(row) for row in self.db.execute('SELECT * FROM incidents WHERE ' + ' AND '.join(where) + ' ORDER BY last_seen DESC LIMIT ?', (*values, limit))]

    def review(self, user, ident, status, note, expected_version):
        if status not in {'ACKNOWLEDGED', 'VERIFIED', 'DISMISSED', 'CLOSED'}:
            raise StoreError('Only human review actions are accepted', 400)
        if user['role'] not in {'admin', 'operator'}:
            raise StoreError('This role cannot review incidents', 403)
        if not isinstance(note, str) or len(note) > 2000 or any(ord(c) < 32 and c not in '\n\t' for c in note):
            raise StoreError('Review note is invalid')
        if type(expected_version) is not int or expected_version < 1:
            raise StoreError('Expected incident version is required')
        with self.transaction():
            row = self.db.execute('SELECT * FROM incidents WHERE organization=? AND incident_id=?', (user['organization'], ident)).fetchone()
            if not row:
                raise StoreError('Incident not found', 404)
            if row['version'] != expected_version:
                raise StoreError('Incident changed; refresh before reviewing', 409)
            if status not in TRANSITIONS[row['status']]:
                raise StoreError('Review transition is not permitted', 409)
            self.db.execute('UPDATE incidents SET status=?,version=version+1,reviewed_at=?,reviewed_by=?,review_note=? WHERE organization=? AND incident_id=?',
                            (status, utc_now(), user['id'], note, user['organization'], ident))
            self._audit(user['organization'], user['id'], 'human_review_' + status.lower(), ident, {'note': note, 'previous_status': row['status'], 'version': row['version'] + 1})
        return self.incident(user['organization'], ident)

    def audit(self, organization, incident_id=None):
        with self.lock:
            if incident_id is not None and not self.incident(organization, incident_id):
                raise StoreError('Incident not found', 404)
            rows = self.db.execute('SELECT id,incident_id,actor,action,timestamp,details FROM audit WHERE organization=?' + (' AND incident_id=?' if incident_id else '') + ' ORDER BY id DESC LIMIT 200', (organization, incident_id) if incident_id else (organization,))
            return [{**dict(row), 'details': json.loads(row['details'])} for row in rows]

    def devices(self, organization):
        with self.lock:
            result = []
            for row in self.db.execute('SELECT device_id,name,last_seen,received_at,health,enabled FROM devices WHERE organization=? ORDER BY name', (organization,)):
                health = json.loads(row['health'])
                reported = datetime.fromisoformat(row['last_seen']).timestamp() if row['last_seen'] else 0
                stale = not row['enabled'] or row['received_at'] is None or time.time() - min(row['received_at'] or 0, reported) > 45
                result.append({'device_id': row['device_id'], 'name': row['name'], 'last_seen': row['last_seen'], 'enabled': bool(row['enabled']), 'status': 'offline' if stale else health.get('status', 'idle'), 'health': health, 'measurement_status': 'historical' if stale else 'latest received heartbeat'})
            return result

    def cameras(self, organization):
        devices = {device['device_id']: device for device in self.devices(organization)}
        with self.lock:
            result = []
            for row in self.db.execute('SELECT camera_id,device_id,name,status,last_frame_at,updated_at FROM cameras WHERE organization=? ORDER BY name', (organization,)):
                value = dict(row)
                if devices[row['device_id']]['status'] == 'offline':
                    value['reported_status'], value['status'] = value['status'], 'offline'
                value['preview_available'] = False
                result.append(value)
            return result

    def models(self, organization):
        devices = {device['device_id']: device for device in self.devices(organization)}
        with self.lock:
            result = []
            for row in self.db.execute('SELECT device_id,payload,updated_at FROM models WHERE organization=? ORDER BY model_id', (organization,)):
                value = json.loads(row['payload'])
                value.update(device_id=row['device_id'], updated_at=row['updated_at'])
                if devices[row['device_id']]['status'] == 'offline':
                    value['reported_status'], value['status'] = value['status'], 'unavailable'
                result.append(value)
            return result

    def summary(self, organization):
        devices = self.devices(organization)
        cameras = self.cameras(organization)
        with self.lock:
            counts = dict(self.db.execute('SELECT status,COUNT(*) FROM incidents WHERE organization=? GROUP BY status', (organization,)))
        return {'cameras': len(cameras), 'devices': len(devices), 'connected_devices': sum(row['status'] != 'offline' for row in devices),
                'pending_incidents': sum(counts.get(key, 0) for key in ('ALERTED', 'ACKNOWLEDGED')), 'verified_incidents': counts.get('VERIFIED', 0),
                'total_incidents': sum(counts.values()), 'incident_counts': counts, 'updated_at': utc_now()}

    def disable_device(self, user, device_id):
        if user['role'] != 'admin':
            raise StoreError('Administrator access required', 403)
        with self.transaction():
            row = self.db.execute('SELECT device_id FROM devices WHERE organization=? AND device_id=?', (user['organization'], device_id)).fetchone()
            if not row:
                raise StoreError('Device not found', 404)
            self.db.execute('UPDATE devices SET enabled=0 WHERE device_id=?', (device_id,))
            self._audit(user['organization'], user['id'], 'device_disabled', details={'device_id': device_id})
        return {'ok': True, 'device_id': device_id, 'enabled': False}

    def settings(self, organization):
        with self.lock:
            row = self.db.execute('SELECT retention_days FROM settings WHERE organization=?', (organization,)).fetchone()
            return {'retention_days': row[0] if row else 7, 'evidence_upload': False, 'external_notifications': False}

    def update_settings(self, user, value):
        if user['role'] != 'admin':
            raise StoreError('Administrator access required', 403)
        if not isinstance(value, dict) or set(value) != {'retention_days'} or type(value['retention_days']) is not int or not 1 <= value['retention_days'] <= 365:
            raise StoreError('Retention must be 1–365 days')
        with self.transaction():
            self.db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(organization) DO UPDATE SET retention_days=excluded.retention_days', (user['organization'], value['retention_days']))
            self._expire(user['organization'])
            self._audit(user['organization'], user['id'], 'retention_updated', details=value)
        return self.settings(user['organization'])
