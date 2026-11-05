"""Owner-private camera metadata; full endpoints and credentials are never SQL data."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from threading import RLock
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import UUID, uuid4

from sentinal.config import ROOT
from sentinal.core.credentials import CredentialStore, CameraCredentials, CredentialError
from sentinal.vision.video_source import SourceSpec

CONNECTION_STATES=frozenset({'idle','connecting','online','reconnecting','offline','error','stopped'})
AUTH_STATES=frozenset({'unknown','not_required','pending','authenticated','failed'})
AI_STATES=frozenset({'idle','active','unavailable','paused','error'})


def utc_now():return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def _name(value):
    if not isinstance(value,str) or not value.strip() or len(value)>120 or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError('Use a camera name of 1 to 120 readable characters')
    return value.strip()


def _identifier(value):
    try:return str(UUID(str(value)))
    except (ValueError,TypeError,AttributeError):raise ValueError('Invalid camera identifier') from None


@dataclass(frozen=True,repr=False)
class CameraRecord:
    camera_id:str
    name:str
    host:str
    connection_type:str
    profile_name:str
    source_kind:str
    camera_device_id:str=field(default='',repr=False)
    device_index:int=0
    remember:bool=False
    connection_health:str='idle'
    last_frame_utc:str|None=None
    authentication_status:str='unknown'
    ai_status:str='idle'
    created_utc:str=''
    updated_utc:str=''

    def __repr__(self):return f'CameraRecord(camera_id={self.camera_id!r}, name={self.name!r}, host={self.host!r})'


@dataclass(frozen=True,repr=False)
class CameraSelection:
    record:CameraRecord
    spec:SourceSpec=field(repr=False)
    endpoint:str=field(default='',repr=False)
    username:str=field(default='',repr=False)
    password:str=field(default='',repr=False)

    def __repr__(self):return f'CameraSelection(camera_id={self.record.camera_id!r}, source_kind={self.spec.kind!r})'


class CameraRegistry:
    def __init__(self,path=None,credentials=None):
        self.path=Path(path or ROOT/'config/cameras/registry.sqlite3').resolve()
        if not self.path.is_relative_to(ROOT):raise ValueError('Camera configuration must stay inside Project Sentinal')
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path.parent.chmod(0o700)
        if self.path.exists() and self.path.stat().st_uid!=os.getuid():raise PermissionError('Camera configuration belongs to another local user')
        self.credentials=credentials or CredentialStore()
        self._lock=RLock()
        self.connection=sqlite3.connect(self.path,timeout=1,check_same_thread=False)
        self.path.chmod(0o600)
        self.connection.row_factory=sqlite3.Row
        with self.connection:
            self.connection.execute('''CREATE TABLE IF NOT EXISTS cameras(
                camera_id TEXT PRIMARY KEY,name TEXT NOT NULL,host TEXT NOT NULL,
                connection_type TEXT NOT NULL,profile_name TEXT NOT NULL,
                source_kind TEXT NOT NULL,camera_device_id TEXT NOT NULL DEFAULT '',
                device_index INTEGER NOT NULL DEFAULT 0,remember INTEGER NOT NULL DEFAULT 0,
                connection_health TEXT NOT NULL DEFAULT 'idle',last_frame_utc TEXT,
                authentication_status TEXT NOT NULL DEFAULT 'unknown',ai_status TEXT NOT NULL DEFAULT 'idle',
                created_utc TEXT NOT NULL,updated_utc TEXT NOT NULL)''')
            self.connection.execute('PRAGMA user_version=1')
            # Runtime health from an earlier app process is never evidence of a live connection.
            self.connection.execute("UPDATE cameras SET connection_health='stopped',ai_status='idle' WHERE connection_health IN ('online','connecting','reconnecting')")

    def _record(self,row):
        if row is None:return None
        values=dict(row);values['remember']=bool(values['remember'])
        return CameraRecord(**values)

    def list_cameras(self):
        with self._lock:return tuple(self._record(row) for row in self.connection.execute('SELECT * FROM cameras ORDER BY name COLLATE NOCASE,camera_id'))

    def get(self,camera_id):
        with self._lock:return self._record(self.connection.execute('SELECT * FROM cameras WHERE camera_id=?',(_identifier(camera_id),)).fetchone())

    def _save(self,record):
        from dataclasses import asdict
        values=asdict(record)
        columns=','.join(values)
        assignments=','.join(f'{key}=excluded.{key}' for key in values if key!='camera_id')
        self.connection.execute(f'INSERT INTO cameras({columns}) VALUES({",".join("?" for _ in values)}) ON CONFLICT(camera_id) DO UPDATE SET {assignments}',tuple(values.values()))

    def upsert_network(self,name,url,username='',password='',profile_name='',remember=False,camera_id=None):
        SourceSpec('stream',url)
        if type(remember) is not bool:raise ValueError('Remember credentials must be explicitly enabled or disabled')
        parts=urlsplit(url)
        if not isinstance(username,str) or not isinstance(password,str) or len(username)>1024 or len(password)>4096:raise ValueError('Camera credentials are invalid')
        if parts.username is not None:
            username=unquote(parts.username);password=unquote(parts.password or '')
        host=f'[{parts.hostname}]' if ':' in parts.hostname else parts.hostname
        netloc=host+(f':{parts.port}' if parts.port else '')
        endpoint=urlunsplit((parts.scheme,netloc,parts.path,parts.query,''))
        profile_name=_name(profile_name) if profile_name else ''
        ident=_identifier(camera_id) if camera_id else str(uuid4())
        previous=self.get(ident) if camera_id else None
        now=utc_now()
        record=CameraRecord(ident,_name(name),parts.hostname,parts.scheme.upper(),profile_name,'stream',remember=bool(remember),
                            authentication_status='pending' if username or password else 'not_required',created_utc=previous.created_utc if previous else now,updated_utc=now)
        with self._lock,self.connection:
            self._save(record)
            # A refused Keychain deletion must leave the previous session
            # connection intact as well as roll back its metadata transaction.
            if previous is not None and previous.remember and not remember:
                self.credentials._backend().delete(ident)
            self.credentials.put(ident,CameraCredentials(endpoint,username,password),remember=remember)
        return record

    def upsert_local(self,name,device_id,device_index=0,camera_id=None):
        SourceSpec('camera',device_index,camera_device_id=device_id,camera_name=name)
        if not device_id:raise ValueError('Select an exact camera identity')
        ident=_identifier(camera_id) if camera_id else str(uuid4());previous=self.get(ident) if camera_id else None
        now=utc_now()
        record=CameraRecord(ident,_name(name),'local','LOCAL','', 'camera',device_id,device_index,False,
                            authentication_status='not_required',created_utc=previous.created_utc if previous else now,updated_utc=now)
        with self._lock,self.connection:
            if previous is not None and previous.source_kind=='stream':self.credentials.delete(ident,remember=previous.remember)
            self._save(record)
        return record

    def resolve(self,camera_id):
        record=self.get(camera_id)
        if record is None:raise ValueError('The selected camera configuration no longer exists')
        if record.source_kind=='camera':
            return CameraSelection(record,SourceSpec('camera',record.device_index,camera_device_id=record.camera_device_id,camera_name=record.name))
        credentials=self.credentials.get(record.camera_id,remember=record.remember)
        if credentials is None:raise CredentialError('This camera address and credentials were session-only. Re-enter them or explicitly save them in Keychain.')
        parts=urlsplit(credentials.endpoint)
        host=f'[{parts.hostname}]' if ':' in parts.hostname else parts.hostname
        netloc=host+(f':{parts.port}' if parts.port else '')
        if credentials.username or credentials.password:
            netloc=quote(credentials.username,safe='')+(':'+quote(credentials.password,safe='') if credentials.password else '')+'@'+netloc
        spec=SourceSpec('stream',urlunsplit((parts.scheme,netloc,parts.path,parts.query,'')))
        return CameraSelection(record,spec,credentials.endpoint,credentials.username,credentials.password)

    def update_health(self,camera_id,connection_health=None,authentication_status=None,ai_status=None,frame_timestamp=None):
        updates={}
        for key,value,choices in [('connection_health',connection_health,CONNECTION_STATES),('authentication_status',authentication_status,AUTH_STATES),('ai_status',ai_status,AI_STATES)]:
            if value is not None:
                if value not in choices:raise ValueError('Invalid camera status')
                updates[key]=value
        if frame_timestamp is not None:
            try:
                timestamp=datetime.fromisoformat(frame_timestamp)
                if timestamp.tzinfo is None:raise ValueError()
            except (TypeError,ValueError):raise ValueError('Frame timestamp must be timezone-aware ISO time') from None
            updates['last_frame_utc']=timestamp.astimezone(timezone.utc).isoformat(timespec='milliseconds')
        updates['updated_utc']=utc_now()
        with self._lock,self.connection:
            cursor=self.connection.execute('UPDATE cameras SET '+','.join(f'{key}=?' for key in updates)+' WHERE camera_id=?',(*updates.values(),_identifier(camera_id)))
            if not cursor.rowcount:raise ValueError('Unknown camera')
        return self.get(camera_id)

    def remove(self,camera_id):
        record=self.get(camera_id)
        if record is None:return
        with self._lock,self.connection:
            self.credentials.delete(record.camera_id,remember=record.remember)
            self.connection.execute('DELETE FROM cameras WHERE camera_id=?',(record.camera_id,))

    def close(self):
        with self._lock:self.connection.close()
