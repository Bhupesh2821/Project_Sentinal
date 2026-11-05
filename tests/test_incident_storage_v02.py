"""Real local SQLite and file-permission tests; no camera/model accuracy claim."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import hashlib
import os
import sqlite3
import stat
from uuid import uuid4
import numpy as np
import pytest
from sentinal.core.incidents import Incident
from sentinal.storage.incident_database import IncidentDatabase,utc_now
from sentinal.storage.evidence_store import EvidenceStore

def incident(**values):
    now=utc_now()
    base=dict(incident_id=str(uuid4()),source_id='unit-camera',session_id='unit-session',category='weapon_firearm',status='ALERTED',confidence=.88,severity=3,model_id='unit-detector',model_version='1',bbox=(1,2,40,45),track_id=1,first_seen=now,last_seen=now,alerted_at=now,alert_latency_ms=500.)
    base.update(values);return Incident(**base)

@pytest.fixture
def db(tmp_path):
    db=IncidentDatabase(tmp_path/'private/incidents.sqlite3')
    yield db
    db.close()

def test_actual_database_persistence_review_audit_and_owner_permissions(db):
    item=incident();db.upsert(item)
    assert stat.S_IMODE(db.path.stat().st_mode)==0o600
    assert stat.S_IMODE(db.path.parent.stat().st_mode)==0o700
    assert db.transition(item.incident_id,'ACKNOWLEDGED','Operator reviewed screen')['status']=='ACKNOWLEDGED'
    assert db.transition(item.incident_id,'VERIFIED','Visible object only; no intent inference')['status']=='VERIFIED'
    assert db.transition(item.incident_id,'CLOSED')['status']=='CLOSED'
    actions=db.audit(item.incident_id)
    assert [r['to_status'] for r in actions]==['ALERTED','ACKNOWLEDGED','VERIFIED','CLOSED']
    restored=IncidentDatabase(db.path)
    try:assert restored.get(item.incident_id)['review_decision']=='CLOSED'
    finally:restored.close()

@pytest.mark.parametrize('target',['VERIFIED','CLOSED','OBSERVED','fake'])
def test_invalid_review_transition_does_not_mutate_history(db,target):
    item=incident();db.upsert(item)
    with pytest.raises(ValueError):db.transition(item.incident_id,target)
    assert db.get(item.incident_id)['status']=='ALERTED'
    assert len(db.audit(item.incident_id))==1

def test_human_dismissal_never_overwritten_by_later_ai_update(db):
    item=incident();db.upsert(item)
    db.transition(item.incident_id,'DISMISSED','Lookalike')
    assert db.upsert(replace(item,confidence=.99))['status']=='DISMISSED'
    assert db.get(item.incident_id)['review_note']=='Lookalike'

@pytest.mark.parametrize('changes',[{'model_version':'2'},{'source_id':'different'},{'category':'fire'}])
def test_immutable_incident_identity(db,changes):
    item=incident();db.upsert(item)
    with pytest.raises(ValueError):db.upsert(replace(item,**changes))

def test_owner_actor_cannot_be_spoofed_and_removed_role_is_denied(db):
    item=incident();db.upsert(item)
    with pytest.raises(PermissionError):db.transition(item.incident_id,'DISMISSED',actor='admin')
    with pytest.raises(PermissionError):IncidentDatabase(db.path,actor='admin')
    db.connection.execute('DELETE FROM authorized_users');db.connection.commit()
    with pytest.raises(PermissionError):db.list_incidents()

def test_queries_filter_date_category_status_and_safe_search(db):
    a,b=incident(),incident(category='fire',status='CANDIDATE',alerted_at=None)
    db.upsert(a);db.upsert(b)
    assert [r['incident_id'] for r in db.list_incidents(category='fire',status='CANDIDATE')]==[b.incident_id]
    today=utc_now()[:10]
    assert len(db.list_incidents(start=today,end=today))==2
    assert db.list_incidents(search="' OR 1=1; --")==[]
    assert len(db.list_incidents(search='unit-camera'))==2

def test_retention_cap_and_expired_records_remove_only_selected_incidents(tmp_path):
    db=IncidentDatabase(tmp_path/'bounded/incidents.sqlite3',max_incidents=10)
    try:
        old=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
        expired=incident(first_seen=old,last_seen=old,alerted_at=old)
        db.upsert(expired);assert db.get(expired.incident_id) is None
        for i in range(12):db.upsert(incident())
        assert len(db.list_incidents())==10
    finally:db.close()

def test_delivery_requests_are_unverified_not_claimed_heard(db):
    item=incident();db.upsert(item)
    db.record_delivery(item.incident_id,'local_audio','submitted')
    row=db.connection.execute('SELECT * FROM notification_deliveries').fetchone()
    assert row['delivered']==0 and 'unverified' in row['detail']
    with pytest.raises(ValueError):db.record_delivery(item.incident_id,'audio','imagined')
    with pytest.raises(KeyError):db.record_delivery('missing','audio','submitted')

def test_evidence_disabled_never_creates_storage(tmp_path):
    store=EvidenceStore(tmp_path/'private/evidence')
    assert store.save_snapshot(incident(),np.zeros((48,64,3),dtype=np.uint8)) is None
    assert not store.path.exists()

def test_snapshot_hash_review_delete_and_audit_tombstone(db):
    item=incident();db.upsert(item)
    store=EvidenceStore(db.path.parent/'evidence')
    result=store.save_snapshot(item,np.full((48,64,3),120,dtype=np.uint8),enabled=True)
    file=store.resolve(result['path'],result['sha256'])
    assert stat.S_IMODE(file.stat().st_mode)==0o600
    assert stat.S_IMODE(store.path.stat().st_mode)==0o700
    db.add_evidence(item.incident_id,file,result['sha256'])
    assert db.evidence(item.incident_id)[0]['sha256']==hashlib.sha256(file.read_bytes()).hexdigest()
    file.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='integrity'):store.resolve(file,result['sha256'])
    assert db.delete_incident(item.incident_id) and not file.exists()
    assert db.get(item.incident_id) is None
    assert db.audit(item.incident_id)[-1]['action']=='incident_deleted'
    assert db.delete_incident(item.incident_id) is False

def test_evidence_refuses_foreign_paths_and_symlinks(db,tmp_path):
    item=incident();db.upsert(item);outside=tmp_path/'unrelated.jpg';outside.write_bytes(b'keep me')
    store=EvidenceStore(db.path.parent/'evidence')
    with pytest.raises(PermissionError):store.resolve(outside)
    with pytest.raises(ValueError):db.add_evidence(item.incident_id,outside,hashlib.sha256(outside.read_bytes()).hexdigest())
    store.path.mkdir();link=store.path/'linked.jpg';link.symlink_to(outside)
    with pytest.raises(ValueError):store.resolve(link)
    assert outside.read_bytes()==b'keep me'

def test_evidence_file_cap_and_retention(tmp_path):
    store=EvidenceStore(tmp_path/'evidence',max_files=1)
    first=store.save_snapshot(incident(),np.zeros((20,20,3),dtype=np.uint8),enabled=True)
    second=store.save_snapshot(incident(),np.ones((20,20,3),dtype=np.uint8),enabled=True)
    assert not os.path.exists(first['path']) and os.path.exists(second['path'])
    old=(datetime.now(timezone.utc)-timedelta(days=8)).timestamp();os.utime(second['path'],(old,old))
    assert len(store.prune())==1 and not os.path.exists(second['path'])

def test_newer_schema_is_rejected_without_migration(tmp_path):
    path=tmp_path/'future.sqlite3'
    con=sqlite3.connect(path);con.execute('PRAGMA user_version=99');con.close()
    with pytest.raises(ValueError,match='newer'):IncidentDatabase(path)
