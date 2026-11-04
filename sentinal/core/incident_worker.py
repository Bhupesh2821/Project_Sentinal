"""Independent bounded incident owner; UI and inference never wait on disk writes."""
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
import logging
import sqlite3
import queue
import threading
from PySide6.QtCore import QThread, Signal
from sentinal.config import ROOT
from sentinal.core.incidents import TemporalEventEngine,TemporalRule,TRANSITIONS,CATEGORIES
from sentinal.core.v02_settings import V02Settings
from sentinal.storage.incident_database import IncidentDatabase,_date,utc_now
from sentinal.storage.evidence_store import EvidenceStore

LOGGER=logging.getLogger(__name__)

class IncidentWorker(QThread):
    incident_changed=Signal(object)
    records_changed=Signal(object)
    audit_ready=Signal(object)
    evidence_ready=Signal(object)
    error=Signal(str)
    def __init__(self,parent=None,path=None):
        super().__init__(parent)
        self.path=Path(path or ROOT/'recordings/incidents/incidents.sqlite3')
        self._commands=queue.Queue(maxsize=64);self._lock=threading.Lock()
        self._packet=None;self._packets=OrderedDict();self._stop=threading.Event();self._wake=threading.Event()
        self.settings=V02Settings();self.persist=False;self.snapshots=False
        self._db=None;self._evidence=None;self._memory={};self.dropped_samples=0
        self.engine=self._engine()
    def _engine(self):
        s=self.settings
        rule=TemporalRule(confidence_threshold=s.confidence,min_consecutive=s.min_consecutive,persistence_s=s.persistence_s,max_gap_s=s.max_gap_s,cooldown_s=s.cooldown_s)
        lower={'weapon_knife','smoke'}
        categories={category:replace(rule,severity=2 if category in lower or category.startswith('ghs_') else 3) for category in CATEGORIES}
        cameras={(source,category):replace(base,**values) for source,values in s.camera_rules.items() for category,base in categories.items()}
        return TemporalEventEngine(rule,camera_rules=cameras,category_rules=categories)
    def _request(self,command,value=None):
        if self._stop.is_set():return False
        try:self._commands.put_nowait((command,value));self._wake.set();return True
        except queue.Full:self.error.emit('Incident command queue is busy. Retry the action.');return False
    def configure(self,settings,persist=False,snapshots=False):
        if not isinstance(settings,V02Settings):raise ValueError('Use validated V0.2 settings')
        if type(persist) is not bool or type(snapshots) is not bool:raise ValueError('Recording preferences must be explicit booleans')
        return self._request('configure',(settings,persist,snapshots and persist))
    def submit_packet(self,packet,source_id):
        if not getattr(packet,'hazard_sampled',False) or self._stop.is_set():return
        with self._lock:
            if source_id in self._packets:
                self._packets.pop(source_id);self.dropped_samples+=1
            elif len(self._packets)>=8:
                self._packets.popitem(last=False);self.dropped_samples+=1
            self._packets[source_id]=(packet,source_id)
            self._packet=(packet,source_id)
        self._wake.set()
    def _take_packet(self):
        with self._lock:
            pending=self._packets.popitem(last=False)[1] if self._packets else None
            self._packet=next(reversed(self._packets.values()),None) if self._packets else None
            if self._packets:self._wake.set()
            return pending
    def review(self,ident,status,note=''):return self._request('review',(ident,status,note))
    def refresh(self,filters=None):return self._request('refresh',filters or {})
    def audit(self,ident):return self._request('audit',ident)
    def preview(self,ident):return self._request('preview',ident)
    def delete(self,ident):return self._request('delete',ident)
    def delivery(self,ident,channel,status,error=''):return self._request('delivery',(ident,channel,status,error))
    def request_shutdown(self):self._stop.set();self._wake.set()
    def _database(self,create=False):
        if self._db is None and (create or self.path.exists()):
            self._db=IncidentDatabase(self.path,retention_days=self.settings.retention_days,max_incidents=self.settings.max_incidents)
            self._evidence=EvidenceStore(self.path.parent/'evidence',retention_days=self.settings.retention_days)
        return self._db
    def _rows(self,filters):
        if not isinstance(filters,dict) or set(filters)-{'search','category','status','start','end','limit'}:raise ValueError('Invalid incident filters')
        start,end=_date(filters.get('start')),_date(filters.get('end'),True)
        db=self._database()
        stored={r['incident_id']:r for r in db.list_incidents(**filters)} if db else {}
        rows={**self._memory,**stored}
        selected=[]
        for row in rows.values():
            if filters.get('category') and row['category']!=filters['category']:continue
            if filters.get('status') and row['status']!=filters['status']:continue
            if filters.get('search') and filters['search'].casefold() not in str(row).casefold():continue
            when=_date(row['first_seen'])
            if start and when<start:continue
            if end and when>end:continue
            selected.append(row)
        return sorted(selected,key=lambda r:r['last_seen'],reverse=True)[:200]
    def _command(self,command,value):
        if command=='configure':
            self.settings,self.persist,self.snapshots=value;self.engine=self._engine()
            if self._db:self._db.close();self._db=None
            if self.persist:self._database(True)
        elif command=='refresh':self.records_changed.emit(self._rows(value))
        elif command=='review':
            ident,status,note=value
            if not isinstance(note,str) or len(note)>2000:raise ValueError('Review note is too long')
            db=self._database()
            if db and db.get(ident):
                row=db.transition(ident,status,note=note);row['persistence_status']='saved'
            else:
                row=dict(self._memory[ident])
                if status not in TRANSITIONS[row['status']]:raise ValueError('This review transition is not allowed')
                row.update(status=status,review_note=note,review_decision=status,reviewed_at=utc_now(),reviewed_by='local session (not persisted)',persistence_status='session_only')
            self._memory[ident]=row;self.incident_changed.emit(row);self.records_changed.emit(self._rows({}))
        elif command=='audit':
            db=self._database();self.audit_ready.emit(db.audit(value) if db else [{'action':'Transient session: audit persistence is disabled'}])
        elif command=='preview':
            db=self._database();row=db.get(value) if db else None
            if not row:raise ValueError('No saved evidence exists for this incident')
            evidence=db.evidence(value)
            if not evidence:raise ValueError('No snapshot was saved; evidence is off by default')
            entry=evidence[-1];path=self._evidence.resolve(entry['path'],entry['sha256']);self.evidence_ready.emit(str(path))
        elif command=='delete':
            db=self._database()
            if db:db.delete_incident(value)
            self._memory.pop(value,None);self.records_changed.emit(self._rows({}))
        elif command=='delivery':
            db=self._database()
            if db and db.get(value[0]):db.record_delivery(*value)
        else:raise ValueError('Unknown incident action')
    def _process(self,packet,source_id):
        for incident in self.engine.process(source_id,packet.session_id,packet.hazards,packet.timestamp,packet.source_time_s):
            row=incident.to_dict()
            old=self._memory.get(incident.incident_id)
            if old and old['status'] in {'ACKNOWLEDGED','VERIFIED','DISMISSED','CLOSED'}:continue
            self._memory[incident.incident_id]=row
            while len(self._memory)>self.settings.max_incidents:self._memory.pop(next(iter(self._memory)))
            if self.persist:
                try:
                    db=self._database(True);db.upsert(incident);row['persistence_status']='saved'
                    if self.snapshots and incident.status=='ALERTED':
                        entry=self._evidence.save_snapshot(incident,packet.frame,enabled=True)
                        if entry:db.add_evidence(incident.incident_id,entry['path'],entry['sha256'])
                except Exception:
                    LOGGER.exception('Local incident persistence failed; alert delivery continues')
                    self.persist=False;self.snapshots=False
                    row['persistence_status']='unavailable'
                    self.error.emit('Incident recording failed. Alerts remain visible; recording is disabled until re-enabled.')
            self.incident_changed.emit(row)
    def run(self):
        try:
            while True:
                self._wake.wait(.1);self._wake.clear()
                for _ in range(16):
                    try:command,value=self._commands.get_nowait()
                    except queue.Empty:break
                    try:self._command(command,value)
                    except Exception as exc:
                        LOGGER.exception('Local incident action failed: %s',command)
                        if command=='configure' or isinstance(exc,(sqlite3.Error,OSError,PermissionError)):
                            self.persist=False;self.snapshots=False
                        self.error.emit(str(exc) if isinstance(exc,(ValueError,PermissionError)) else 'Incident storage or review failed. Check local permissions and diagnostics.')
                if self._stop.is_set():
                    with self._lock:self._packet=None;self._packets.clear()
                    if self._commands.empty():break
                    continue
                pending=self._take_packet()
                if pending:
                    try:self._process(*pending)
                    except Exception:
                        self.persist=False;self.error.emit('Incident processing/storage is unavailable. Monitoring can continue; check diagnostics before relying on alerts.')
        finally:
            with self._lock:self._packet=None;self._packets.clear()
            if self._db:self._db.close();self._db=None
