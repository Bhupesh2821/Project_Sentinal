"""Bounded worker/local-output contracts with synthetic detector DTOs."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
from types import SimpleNamespace
import time
import pytest
from PySide6.QtWidgets import QApplication
from sentinal.core.incident_worker import IncidentWorker
from sentinal.core.v02_settings import V02Settings
from sentinal.core.incidents import Incident
from sentinal.core.alerts import AlertDispatcher,InApplicationAdapter,UnconfiguredExternalAdapter
from sentinal.storage.incident_database import utc_now


def obs():return SimpleNamespace(category='weapon_firearm',confidence=.9,bbox=(1,2,20,30),track_id=1,model_id='unit-model',model_version='v1')
def spin(app,predicate,seconds=3):
    limit=time.monotonic()+seconds
    while time.monotonic()<limit:
        app.processEvents()
        if predicate():return
        time.sleep(.003)
    raise AssertionError('Worker did not complete expected operation')


def test_worker_default_off_single_mailbox_and_command_cap(tmp_path,packet):
    app=QApplication.instance() or QApplication([])
    worker=IncidentWorker(path=tmp_path/'not-created/incidents.sqlite3')
    assert not worker.persist and not worker.snapshots and not worker.path.exists()
    for i in range(10):worker.submit_packet(replace(packet,hazard_sampled=True,frame_index=i),'cam')
    assert worker.dropped_samples==9 and worker._packet[0].frame_index==9
    worker.submit_packet(replace(packet,hazard_sampled=False,frame_index=20),'cam')
    assert worker._packet[0].frame_index==9
    for _ in range(64):assert worker.refresh()
    assert not worker.refresh()
    worker.request_shutdown()
    worker.submit_packet(replace(packet,hazard_sampled=True,frame_index=30),'cam')
    assert worker._packet[0].frame_index==9
    assert not worker.refresh()


def test_optional_storage_failure_keeps_visible_real_service_events(tmp_path,packet,monkeypatch):
    app=QApplication.instance() or QApplication([])
    worker=IncidentWorker(path=tmp_path/'unwritten/incidents.sqlite3');rows=[];errors=[]
    worker.incident_changed.connect(rows.append);worker.error.connect(errors.append)
    worker.persist=True
    def fail(*args):raise OSError('simulated disk-full failure')
    monkeypatch.setattr(worker,'_database',fail)
    worker._process(replace(packet,hazard_sampled=True,hazards=(obs(),),source_time_s=0),'cam')
    worker._process(replace(packet,hazard_sampled=True,hazards=(obs(),),source_time_s=.5),'cam')
    worker._process(replace(packet,hazard_sampled=True,hazards=(obs(),),source_time_s=1),'cam')
    assert [row['status'] for row in rows]==['OBSERVED','CANDIDATE','ALERTED']
    assert errors and not worker.persist and not worker.path.exists()
    assert rows[0]['persistence_status']=='unavailable'


def test_real_async_thread_persists_acknowledges_and_stops(tmp_path,packet):
    app=QApplication.instance() or QApplication([])
    worker=IncidentWorker(path=tmp_path/'private/incidents.sqlite3');rows=[];errors=[];lists=[]
    worker.incident_changed.connect(rows.append);worker.error.connect(errors.append);worker.records_changed.connect(lists.append)
    worker.configure(V02Settings(min_consecutive=2,persistence_s=.1),persist=True)
    worker.start()
    try:
        worker.submit_packet(replace(packet,hazard_sampled=True,hazards=(obs(),),source_time_s=0),'cam')
        spin(app,lambda:len(rows)>=1)
        worker.submit_packet(replace(packet,hazard_sampled=True,hazards=(obs(),),source_time_s=.2),'cam')
        spin(app,lambda:any(r['status']=='ALERTED' for r in rows))
        ident=rows[-1]['incident_id'];worker.review(ident,'ACKNOWLEDGED','Unit review')
        spin(app,lambda:any(r['status']=='ACKNOWLEDGED' for r in rows))
        worker.review(ident,'DISMISSED','Lookalike');spin(app,lambda:any(r['status']=='DISMISSED' for r in rows))
        worker.refresh({'end':utc_now()[:10]});spin(app,lambda:len(lists)>=3)
        assert worker.path.exists() and not errors
        # A review accepted immediately before Close must survive shutdown.
        assert worker.review(ident,'CLOSED','Closing after review')
    finally:
        worker.request_shutdown();assert worker.wait(3000)
        app.processEvents()
    from sentinal.storage.incident_database import IncidentDatabase
    db=IncidentDatabase(worker.path)
    try:assert db.get(ident)['status']=='CLOSED'
    finally:db.close()


def test_worker_configuration_validated_and_evidence_requires_recording(tmp_path):
    worker=IncidentWorker(path=tmp_path/'incidents.sqlite3')
    with pytest.raises(ValueError):worker.configure({})
    with pytest.raises(ValueError):worker.configure(V02Settings(),persist='yes')
    assert worker.configure(V02Settings(),persist=False,snapshots=True)
    command,value=worker._commands.get_nowait();worker._command(command,value)
    assert not worker.persist and not worker.snapshots and not worker.path.exists()


def test_dispatcher_deduplicates_reports_unconfigured_external_and_closes():
    row=Incident('alert','cam','session','fire','ALERTED',.8,3,'test','1',(1,2,20,30),None,utc_now(),utc_now(),utc_now(),500)
    received=[];dispatcher=AlertDispatcher([InApplicationAdapter(received.append),UnconfiguredExternalAdapter('email')])
    try:
        assert dispatcher.publish(row)
        assert not dispatcher.publish(row)
    finally:assert dispatcher.close()
    deliveries=dispatcher.take_deliveries()
    assert len(received)==1 and len(deliveries)==2
    assert deliveries[0].delivered and not deliveries[1].delivered
    assert not dispatcher.publish(replace(row,incident_id='second'))


def test_local_alert_optin_cooldown_and_validation(monkeypatch):
    from sentinal.interface import local_alerts as module
    app=QApplication.instance() or QApplication([])
    class Sound:
        class Status:Ready=1
        def __init__(self,*args):self.plays=0;self.volume=None
        def setLoopCount(self,*args):pass
        def setSource(self,*args):pass
        def setVolume(self,value):self.volume=value
        def status(self):return self.Status.Ready
        def play(self):self.plays+=1
        def stop(self):pass
        def isPlaying(self):return False
    class Tray:
        class MessageIcon:Warning=1
        def __init__(self,*args):self.messages=[]
        def setIcon(self,*args):pass
        def setVisible(self,*args):pass
        def showMessage(self,*args):self.messages.append(args)
        def hide(self):pass
        @staticmethod
        def isSystemTrayAvailable():return True
        @staticmethod
        def supportsMessages():return True
    monkeypatch.setattr(module,'QSoundEffect',Sound);monkeypatch.setattr(module,'QSystemTrayIcon',Tray)
    monkeypatch.setattr(module.time,'monotonic',lambda:100)
    output=module.LocalAlertOutput();deliveries=[];output.delivery.connect(deliveries.append)
    item={'status':'ALERTED','incident_id':'one','severity':3,'category':'fire','last_seen':utc_now()}
    output.send(item)
    assert not output.sound.plays and not output.tray.messages
    output.configure(audio=True,desktop=True,volume=.25,severity=3)
    output.send({**item,'incident_id':'two'});output.send({**item,'incident_id':'three'})
    assert output.sound.plays==1 and len(output.tray.messages)==2 and output.sound.volume==.25
    assert all(r['status']=='submitted' for r in deliveries)
    for settings in [{'volume':float('nan')},{'volume':2},{'severity':5},{'audio':'yes'}]:
        with pytest.raises(ValueError):output.configure(**settings)
    output.close()


def test_category_severity_and_camera_override_keep_global_thresholds(tmp_path):
    worker=IncidentWorker(path=tmp_path/'unused.sqlite3')
    worker.settings=V02Settings(confidence=.8,persistence_s=2,camera_rules={'cam':{'confidence_threshold':.9}})
    engine=worker._engine()
    assert engine._rule('other','weapon_firearm').severity==3
    assert engine._rule('other','fire').severity==3
    for category in ('weapon_knife','smoke','ghs_health'):
        assert engine._rule('cam',category).severity==2
        assert engine._rule('cam',category).confidence_threshold==.9
        assert engine._rule('cam',category).persistence_s==2
