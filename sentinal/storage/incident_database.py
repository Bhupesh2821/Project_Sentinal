"""Owner-only local incident history. Separate migrations preserve V0.1 metadata."""
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import sqlite3
from sentinal.config import ROOT
from sentinal.core.incidents import Incident,STATES,CATEGORIES,TRANSITIONS,validate_timestamp


def utc_now():return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def project_path(value):
    original=Path(value).expanduser()
    if original.is_symlink():raise ValueError('Symbolic-link storage targets are not allowed')
    path=original.resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Incident storage must remain inside Project Sentinal')
    return path


def _date(value,end=False):
    if value is None:return None
    if not isinstance(value,str):raise ValueError('Date filter must be ISO text')
    if len(value)==10:
        parsed=datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        if end:parsed+=timedelta(days=1,microseconds=-1)
    else:
        validate_timestamp(value);parsed=datetime.fromisoformat(value)
    return parsed.astimezone(timezone.utc).isoformat(timespec='milliseconds')


class IncidentDatabase:
    schema_version=1
    def __init__(self,path=None,retention_days=7,max_incidents=10000,actor=None):
        if type(retention_days) is not int or not 1<=retention_days<=365:raise ValueError('Retention must be 1 to 365 days')
        if type(max_incidents) is not int or not 10<=max_incidents<=100000:raise ValueError('Incident cap must be 10 to 100000')
        self.owner_uid=os.getuid();self.actor='local:'+str(self.owner_uid)
        if actor is not None and actor!=self.actor:raise PermissionError('Only the current macOS account may administer local incidents')
        self.retention_days=retention_days;self.max_incidents=max_incidents
        self.path=project_path(path or ROOT/'recordings/incidents/incidents.sqlite3')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.parent.stat().st_uid!=self.owner_uid:raise PermissionError('Incident folder belongs to a different account')
        self.path.parent.chmod(0o700)
        try:
            descriptor=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(descriptor)
        except FileExistsError:pass
        if self.path.stat().st_uid!=self.owner_uid:raise PermissionError('Incident database belongs to a different account')
        self.path.chmod(0o600)
        self.connection=sqlite3.connect(str(self.path),timeout=1.0)
        self.connection.row_factory=sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON');self.connection.execute('PRAGMA secure_delete=ON')
        version=self.connection.execute('PRAGMA user_version').fetchone()[0]
        if version>self.schema_version:
            self.connection.close();raise ValueError('This incident database needs a newer SENTINAL version')
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS authorized_users(actor TEXT PRIMARY KEY,uid INTEGER NOT NULL,role TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cameras(source_id TEXT PRIMARY KEY,name TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS detection_models(model_id TEXT NOT NULL,version TEXT NOT NULL,PRIMARY KEY(model_id,version));
        CREATE TABLE IF NOT EXISTS incidents(incident_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,session_id TEXT NOT NULL,category TEXT NOT NULL,status TEXT NOT NULL,confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1),severity INTEGER NOT NULL CHECK(severity>=1 AND severity<=4),first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS incident_time ON incidents(first_seen);
        CREATE INDEX IF NOT EXISTS incident_category ON incidents(category,status);
        CREATE TABLE IF NOT EXISTS evidence(evidence_id TEXT PRIMARY KEY,incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,path TEXT NOT NULL,sha256 TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY,incident_id TEXT,actor TEXT NOT NULL,action TEXT NOT NULL,from_status TEXT,to_status TEXT,note TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS audit_incident ON audit_events(incident_id,id);
        CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'Audit records cannot be edited'); END;
        CREATE TABLE IF NOT EXISTS notification_deliveries(id INTEGER PRIMARY KEY,incident_id TEXT NOT NULL,channel TEXT NOT NULL,delivered INTEGER NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sensor_devices(sensor_id TEXT PRIMARY KEY,kind TEXT NOT NULL,state TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{}');
        PRAGMA user_version=1;
        """)
        self.connection.execute('INSERT OR IGNORE INTO authorized_users VALUES(?,?,?,?)',(self.actor,self.owner_uid,'owner',utc_now()))
        self.connection.commit();self.prune()
    def _authorize(self,actor=None):
        if os.getuid()!=self.owner_uid or (actor is not None and actor!=self.actor):raise PermissionError('Incident access is restricted to the current local account')
        row=self.connection.execute('SELECT role FROM authorized_users WHERE actor=? AND uid=?',(self.actor,self.owner_uid)).fetchone()
        if row is None or row['role']!='owner':raise PermissionError('This account may not administer incident history')
    def _audit(self,incident_id,action,old=None,new=None,note=''):
        self.connection.execute('INSERT INTO audit_events(incident_id,actor,action,from_status,to_status,note,created_at) VALUES(?,?,?,?,?,?,?)',(incident_id,self.actor,action,old,new,str(note)[:2000],utc_now()))
    def get(self,incident_id):
        self._authorize()
        row=self.connection.execute('SELECT payload FROM incidents WHERE incident_id=?',(incident_id,)).fetchone()
        return json.loads(row['payload']) if row else None
    def upsert(self,incident):
        self._authorize()
        if not isinstance(incident,Incident):raise TypeError('Use validated Incident observations')
        if incident.status not in {'OBSERVED','CANDIDATE','ALERTED'}:raise ValueError('Human review changes require transition()')
        existing=self.get(incident.incident_id)
        if existing and (existing['source_id']!=incident.source_id or existing['session_id']!=incident.session_id or existing['category']!=incident.category or existing['model_id']!=incident.model_id or existing['model_version']!=incident.model_version):raise ValueError('Incident identity cannot change')
        if existing and existing['status'] in {'ACKNOWLEDGED','VERIFIED','DISMISSED','CLOSED'}:return existing
        rank={'OBSERVED':0,'CANDIDATE':1,'ALERTED':2}
        if existing and rank[existing['status']]>rank[incident.status]:return existing
        data=incident.to_dict();data['first_seen']=_date(existing['first_seen'] if existing else incident.first_seen);data['last_seen']=_date(incident.last_seen)
        data['evidence']=existing.get('evidence',[]) if existing else []
        with self.connection:
            self.connection.execute('INSERT OR IGNORE INTO cameras(source_id,name) VALUES(?,?)',(incident.source_id,incident.source_id))
            self.connection.execute('INSERT OR IGNORE INTO detection_models VALUES(?,?)',(incident.model_id,incident.model_version))
            self.connection.execute('INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(incident_id) DO UPDATE SET status=excluded.status,confidence=excluded.confidence,severity=excluded.severity,last_seen=excluded.last_seen,payload=excluded.payload',(incident.incident_id,incident.source_id,incident.session_id,incident.category,incident.status,incident.confidence,incident.severity,data['first_seen'],data['last_seen'],json.dumps(data,separators=(',',':'))))
            if not existing or existing['status']!=incident.status:self._audit(incident.incident_id,'automated_observation',existing['status'] if existing else None,incident.status)
        self.prune();return data

    def list_incidents(self,search='',category=None,status=None,start=None,end=None,limit=200):
        self._authorize()
        if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Query limit must be 1 to 1000')
        if not isinstance(search,str) or len(search)>256:raise ValueError('Search text is invalid')
        clauses=[];values=[]
        if category is not None:
            if category not in CATEGORIES:raise ValueError('Unknown category filter')
            clauses.append('category=?');values.append(category)
        if status is not None:
            if status not in STATES:raise ValueError('Unknown lifecycle filter')
            clauses.append('status=?');values.append(status)
        for operator,value in [('>=',_date(start)),('<=',_date(end,True))]:
            if value is not None:clauses.append('first_seen'+operator+'?');values.append(value)
        if search.strip():
            clauses.append('(category LIKE ? OR source_id LIKE ? OR incident_id LIKE ?)')
            values.extend(['%'+search.strip()+'%']*3)
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        return [json.loads(row['payload']) for row in self.connection.execute('SELECT payload FROM incidents'+where+' ORDER BY first_seen DESC,incident_id LIMIT ?',(*values,limit))]
    def transition(self,incident_id,new_status,note='',actor=None):
        self._authorize(actor)
        if not isinstance(note,str) or len(note)>2000:raise ValueError('Review note is too long')
        current=self.get(incident_id)
        if current is None:raise KeyError('Incident no longer exists')
        old=current['status']
        if new_status not in TRANSITIONS[old]:raise ValueError('Review transition '+old+' → '+str(new_status)+' is not allowed')
        current.update(status=new_status,review_decision=new_status,reviewed_by=self.actor,reviewed_at=utc_now(),review_note=note)
        with self.connection:
            self.connection.execute('UPDATE incidents SET status=?,payload=? WHERE incident_id=?',(new_status,json.dumps(current,separators=(',',':')),incident_id))
            self._audit(incident_id,'human_review',old,new_status,note)
        return current
    def audit(self,incident_id=None,limit=500):
        self._authorize()
        if type(limit) is not int or not 1<=limit<=2000:raise ValueError('Audit limit must be 1 to 2000')
        if incident_id is None:rows=self.connection.execute('SELECT * FROM audit_events ORDER BY id DESC LIMIT ?',(limit,))
        else:rows=self.connection.execute('SELECT * FROM audit_events WHERE incident_id=? ORDER BY id LIMIT ?',(incident_id,limit))
        return [dict(row) for row in rows]
    def add_evidence(self,incident_id,path,sha256):
        from uuid import uuid4
        self._authorize();target=project_path(path)
        if not target.is_relative_to((self.path.parent/'evidence').resolve()) or not target.is_file() or target.stat().st_uid!=self.owner_uid:raise ValueError('Evidence file is unavailable or outside the owned private evidence folder')
        if not isinstance(sha256,str) or len(sha256)!=64 or any(c not in '0123456789abcdef' for c in sha256):raise ValueError('Invalid evidence checksum')
        import hashlib
        if hashlib.sha256(target.read_bytes()).hexdigest()!=sha256:raise ValueError('Evidence integrity check failed')
        data=self.get(incident_id)
        if data is None:raise KeyError('Incident no longer exists')
        record={'evidence_id':str(uuid4()),'path':str(target.relative_to(ROOT)),'sha256':sha256,'created_at':utc_now()}
        data.setdefault('evidence',[]).append(record)
        with self.connection:
            self.connection.execute('INSERT INTO evidence VALUES(?,?,?,?,?)',(record['evidence_id'],incident_id,record['path'],sha256,record['created_at']))
            self.connection.execute('UPDATE incidents SET payload=? WHERE incident_id=?',(json.dumps(data,separators=(',',':')),incident_id))
            self._audit(incident_id,'evidence_saved')
        return record
    def evidence(self,incident_id):
        self._authorize()
        return [dict(row) for row in self.connection.execute('SELECT evidence_id,path,sha256,created_at FROM evidence WHERE incident_id=? ORDER BY created_at,evidence_id',(incident_id,))]
    def record_delivery(self,incident_id,channel,status,error=''):
        self._authorize()
        if not isinstance(channel,str) or not channel or len(channel)>64:raise ValueError('Invalid notification channel')
        if type(status) is bool:delivered=status
        elif status in {'shown','displayed','played','delivered','sent','success'}:delivered=True
        elif status in {'failed','disabled','suppressed','unavailable','not_configured','submitted'}:delivered=False
        else:raise ValueError('Unknown delivery status')
        if self.get(incident_id) is None:raise KeyError('Incident no longer exists')
        detail=error or (status if isinstance(status,str) else '')
        if status=='submitted' and not error:detail='submitted: platform accepted request; presentation/hearing is unverified'
        with self.connection:self.connection.execute('INSERT INTO notification_deliveries(incident_id,channel,delivered,detail,created_at) VALUES(?,?,?,?,?)',(incident_id,channel,int(delivered),str(detail)[:256],utc_now()))
    def _unlink_evidence(self,incident_ids):
        for ident in incident_ids:
            for row in self.connection.execute('SELECT path FROM evidence WHERE incident_id=?',(ident,)).fetchall():
                target=project_path(ROOT/row['path'])
                # Only this store's private evidence subtree may be removed.
                allowed=(self.path.parent/'evidence').resolve()
                if target.is_relative_to(allowed) and target.is_file() and target.stat().st_uid==self.owner_uid:target.unlink()
    def delete_incident(self,incident_id,actor=None):
        self._authorize(actor)
        if self.get(incident_id) is None:return False
        self._unlink_evidence([incident_id])
        with self.connection:
            self.connection.execute('DELETE FROM incidents WHERE incident_id=?',(incident_id,))
            self._audit(incident_id,'incident_deleted',note='Local record and referenced owned evidence removed; storage-device secure erasure is not guaranteed.')
        return True
    def prune(self):
        self._authorize()
        cutoff=(datetime.now(timezone.utc)-timedelta(days=self.retention_days)).isoformat(timespec='milliseconds')
        expired=[row[0] for row in self.connection.execute('SELECT incident_id FROM incidents WHERE last_seen<?',(cutoff,))]
        capped=[row[0] for row in self.connection.execute('SELECT incident_id FROM incidents ORDER BY first_seen DESC LIMIT -1 OFFSET ?',(self.max_incidents,))]
        identifiers=set(expired+capped);self._unlink_evidence(identifiers)
        with self.connection:
            self.connection.executemany('DELETE FROM incidents WHERE incident_id=?',[(i,) for i in identifiers])
            self.connection.execute('DELETE FROM audit_events WHERE created_at<?',(cutoff,))
            self.connection.execute('DELETE FROM audit_events WHERE id IN(SELECT id FROM audit_events ORDER BY id DESC LIMIT -1 OFFSET ?)',(self.max_incidents*10,))
            self.connection.execute('DELETE FROM notification_deliveries WHERE created_at<?',(cutoff,))
            self.connection.execute('DELETE FROM notification_deliveries WHERE id IN(SELECT id FROM notification_deliveries ORDER BY id DESC LIMIT -1 OFFSET ?)',(self.max_incidents*10,))
        return len(identifiers)
    def close(self):self.connection.close()
