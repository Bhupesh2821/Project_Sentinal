"""Synthetic UI contracts only; native real-model evidence is tested separately."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication
from sentinal.config import AppConfig
from sentinal.core.v02_settings import V02Settings
from sentinal.interface import main_window
from sentinal.interface.control_center import ControlCenter
from sentinal.interface.video_panel import VideoPanel
from sentinal.vision.types import FramePacket,utc_now
from sentinal.vision.specialized import HazardObservation

class Worker(QObject):
    state_changed=Signal(str,str);error=Signal(str);metadata_failed=Signal(str);finished=Signal();playback_changed=Signal(object)
    def __init__(self,*args):super().__init__();self.running=False;self.starts=[];self.hazards={};self.consumer=None
    def start(self):self.running=True
    def isRunning(self):return self.running
    def request_start(self,spec):self.starts.append(spec);self.state_changed.emit('running','Unit test source')
    def request_shutdown(self):self.running=False;QTimer.singleShot(0,self.finished.emit)
    def request_stop(self):self.state_changed.emit('stopped','Unit test stopped')
    def set_options(self,**kwargs):pass
    def set_hazard_options(self,**kwargs):self.hazards=kwargs
    def set_incident_consumer(self,consumer):self.consumer=consumer
    def take_latest(self):return None

class Service(QObject):
    records_changed=Signal(object);incident_changed=Signal(object);audit_ready=Signal(object);evidence_ready=Signal(object)
    dropped_samples=0
    def __init__(self):super().__init__();self.actions=[]
    def refresh(self,filters):self.actions.append(('refresh',filters))
    def review(self,*args):self.actions.append(('review',args))

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

def spin(app,predicate):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():return
        time.sleep(.005)
    raise AssertionError('UI shutdown timed out')

@pytest.fixture
def window(app,monkeypatch):
    monkeypatch.setattr(main_window,'InferenceWorker',Worker)
    monkeypatch.setattr(main_window,'discover_cameras',lambda:[])
    monkeypatch.setattr(main_window,'VideoLibrary',lambda:SimpleNamespace(list_entries=lambda:[]))
    monkeypatch.setattr(V02Settings,'load',classmethod(lambda cls:cls()))
    view=main_window.MainWindow(AppConfig());view.show();app.processEvents()
    yield view
    view.close();spin(app,lambda:not view.isVisible())

def incident(status='ALERTED'):
    return dict(incident_id='test-incident',source_id='source-unit-test',session_id='session',category='weapon_handgun',status=status,confidence=.91,severity=3,model_id='unit-test',model_version='1',bbox=[10,10,70,70],track_id=1,first_seen=utc_now(),last_seen=utc_now(),alerted_at=utc_now(),alert_latency_ms=1000)

def test_default_options_never_start_or_record(window):
    assert not window.hazards_toggle.isChecked()
    assert not window.incident_record_toggle.isChecked()
    assert not window.evidence_toggle.isChecked()
    assert not window.audio_toggle.isChecked()
    assert not window.desktop_toggle.isChecked()
    assert not window.worker.starts
    assert window._incident_worker is None

def test_hazard_controls_connect_bounded_service_and_stop(window,app):
    window.hazards_toggle.setChecked(True)
    assert window._incident_worker.isRunning()
    assert window.worker.hazards['enabled']==('weapons','fire_smoke')
    assert callable(window.worker.consumer)
    assert not window._incident_worker.persist
    window.hazards_toggle.setChecked(False)
    assert window.worker.hazards['enabled']==()
    assert window.worker.consumer is None

def test_alert_banner_is_uncertain_and_review_is_visible(window):
    window._incident_changed(incident())
    assert window.incident_banner.isVisible()
    assert 'POSSIBLE HANDGUN' in window.incident_banner.text()
    assert 'Awaiting human verification' in window.incident_banner.text()
    window._incident_changed(incident('DISMISSED'))
    assert 'DISMISSED' in window.incident_banner.text()
    assert 'for this session' in window.incident_banner.text()

def test_own_video_keeps_source_identity_private_and_explicit(window,tmp_path):
    path=tmp_path/'private-video-name.mp4';window.load_video(path)
    assert not window.worker.starts
    window.start_monitoring()
    assert len(window.worker.starts)==1
    assert window._active_source_id.startswith('source-')
    assert str(path) not in window._active_source_id

def test_incident_review_buttons_enforce_state_machine(app):
    service=Service();center=ControlCenter(service,V02Settings())
    center.show_records([incident()]);center.table.selectRow(0);app.processEvents()
    assert center.review_buttons['ACKNOWLEDGED'].isEnabled()
    assert not center.review_buttons['VERIFIED'].isEnabled()
    center.note.setText('Reviewed test fixture');center.review('ACKNOWLEDGED')
    assert service.actions[-1]==('review',('test-incident','ACKNOWLEDGED','Reviewed test fixture'))
    center.show_records([incident('ACKNOWLEDGED')]);center.table.selectRow(0)
    assert center.review_buttons['VERIFIED'].isEnabled()
    center.close()

def test_hazard_overlay_uses_source_coordinates_without_modifying_frame(app):
    frame=np.zeros((100,100,3),np.uint8)
    hazard=HazardObservation('fire',.85,(20,20,80,80),1,'unit-test','1','fire_smoke')
    packet=FramePacket(frame,(),'unit','test',1,utc_now(),0,1,1,1,'cpu',hazards=(hazard,),hazard_sampled=True)
    panel=VideoPanel();panel.resize(500,500);panel.set_packet(packet);panel.show();app.processEvents()
    annotated=panel.grab().toImage()
    assert any(annotated.pixelColor(x,200).red()>180 for x in range(98,105))
    assert not frame.any()
    panel.set_annotations(False,False,False);app.processEvents();plain=panel.grab().toImage()
    assert all(plain.pixelColor(x,200).red()==0 for x in range(98,105))
    panel.close()

def test_runtime_diagnostics_never_mark_stopped_as_monitoring(app):
    service=Service();center=ControlCenter(service,V02Settings())
    center.update_runtime('stopped','source')
    assert center.summary.text().startswith('Inactive')
    assert 'No active inference' in center.ai_health.toPlainText()
    center.close()


def test_terminal_state_immediately_refreshes_operator_center(window,app):
    window.open_control_center();app.processEvents()
    window._last_runtime_refresh=time.monotonic()
    window._on_state('running','Unit source is running')
    assert window._control_center.summary.text().startswith('Monitoring')
    window._last_runtime_refresh=time.monotonic()
    window._on_state('stopped','Unit source stopped')
    assert window._control_center.summary.text().startswith('Inactive')
    assert 'No active inference' in window._control_center.ai_health.toPlainText()


def test_unexpected_worker_exit_clears_monitoring_status(window):
    window._on_state('running','Unit source is running')
    window.worker.running=False;window._worker_finished()
    assert window._state=='error' and not window._busy
    assert 'MONITORING' not in window.status_chip.text()
    assert 'unavailable' in window.connection_label.text().lower()


def test_unrelated_review_cannot_hide_pending_alert(window):
    window._incident_changed(incident())
    pending=window.incident_banner.text()
    other={**incident('DISMISSED'),'incident_id':'older-different-incident'}
    window._incident_changed(other)
    assert window.incident_banner.text()==pending


def test_failed_detectors_do_not_claim_sample_is_clear(window):
    window.hazards_toggle.setChecked(True);window._on_state('running','Unit source')
    packet=FramePacket(np.zeros((48,64,3),np.uint8),(),'unit','source',1,utc_now(),0,1,1,1,'cpu',hazard_sampled=True,detector_health={'weapons':{'status':'unavailable'}})
    packets=iter([packet]);window.worker.take_latest=lambda:next(packets,None)
    window._poll_frame()
    assert 'incomplete' in window.threat_label.text()
    assert 'weapons' in window.threat_label.text()
    assert 'No possible hazards' not in window.threat_label.text()
    window._on_state('eof','Complete')
    assert 'No current hazard analysis' in window.threat_label.text()


def test_review_error_does_not_disable_working_recording(window):
    from PySide6.QtCore import QSignalBlocker
    window.hazards_toggle.setChecked(True)
    window._incident_worker.persist=True
    with QSignalBlocker(window.incident_record_toggle):window.incident_record_toggle.setChecked(True)
    window._incident_error('This review transition is not allowed')
    assert window.incident_record_toggle.isChecked()
    window._incident_worker.persist=False
    window._incident_error('Incident recording failed')
    assert not window.incident_record_toggle.isChecked()


def test_missing_optional_ghs_is_disabled_in_settings(app):
    center=ControlCenter(Service(),V02Settings(detectors=('weapons','ghs')))
    assert not center.detector_checks['ghs'].isEnabled()
    assert not center.detector_checks['ghs'].isChecked()
    assert 'unavailable' in center.detector_checks['ghs'].text()
    center.close()


@pytest.mark.parametrize('state',['stopped','error','paused','eof','reconnecting'])
def test_last_diagnostics_are_historical_when_inference_is_inactive(app,state):
    import json
    center=ControlCenter(Service(),V02Settings())
    packet=FramePacket(np.zeros((48,64,3),np.uint8),(),'unit','source',15,utc_now(),.5,12,22,23,'cpu',diagnostics={'memory_rss_mb':123},detector_health={'weapons':{'status':'active'}})
    center.update_runtime('running','Unit recorded clip',packet)
    center.update_runtime(state,'Unit recorded clip')
    result=json.loads(center.diagnostics.toPlainText())
    assert result['source_state']==state and result['monitoring_active'] is False
    assert result['measurement_status']=='Historical last sample; no active inference'
    assert result['frame_timestamp_utc']==packet.timestamp and result['inference_ms']==22
    assert result['sample_source']=='Unit recorded clip' and result['memory_rss_mb']==123
    assert 'No active inference' in center.ai_health.toPlainText()
    # A queued final packet must also remain explicitly historical.
    center.update_runtime(state,'Unit recorded clip',packet)
    assert json.loads(center.diagnostics.toPlainText())['monitoring_active'] is False
    assert 'No active inference' in center.ai_health.toPlainText()
    center.close()


def test_retained_final_frame_does_not_display_active_processing_rate(window):
    packet=FramePacket(np.zeros((48,64,3),np.uint8),(),'unit','source',15,utc_now(),.5,12,22,23,'cpu')
    window._on_state('running','Unit source')
    packets=iter([packet]);window.worker.take_latest=lambda:next(packets,None)
    window._poll_frame()
    assert window.statistics.values['fps'].text()=='12.0'
    packets=iter([packet]);window.worker.take_latest=lambda:next(packets,None)
    window._on_state('eof','Source complete')
    assert window.last_packet is packet
    assert window.statistics.values['fps'].text()=='—'
    assert window.statistics.values['latency'].text()=='—'


def test_no_enabled_models_clears_previous_hazard_text(window):
    window.hazards_toggle.setChecked(True)
    window.threat_label.setText('POSSIBLE old observation')
    window.hazard_settings=replace(V02Settings(),detectors=())
    window._hazard_options_changed()
    assert 'No hazard detectors enabled' in window.threat_label.text()


def test_connected_settings_are_inert_until_explicit_enable(window):
    window.open_connected_settings()
    dialog=window._connected_dialog;bridge=window._edge_bridge
    assert dialog.isVisible() and not dialog.enabled.isChecked()
    assert not bridge.is_running and bridge.publisher is None
    assert dialog.url.text()=='' and dialog.secret.text()==''
    assert not dialog.local.isChecked() and not window.worker.starts
    dialog.enabled.setChecked(True)
    assert not dialog.enabled.isChecked() and bridge.publisher is None
    assert 'could not start' in dialog.message.text()


def test_outbound_health_never_contains_stream_credentials_or_stale_live_metrics(window):
    import json
    from sentinal.vision.video_source import SourceSpec
    window._current_spec=SourceSpec('stream','rtsp://account:private-password@127.0.0.1:18554/private')
    window._active_source_id='source-safe-identity'
    window.source_name.setText('rtsp://account:private-password@127.0.0.1:18554/private')
    window._state='stopped';window._busy=False
    value=window._connected_health();encoded=json.dumps(value)
    assert 'rtsp://' not in encoded and 'private-password' not in encoded and 'account:' not in encoded
    assert value['health']=={'status':'idle'}
    assert value['cameras'][0]['name']=='Selected local source'
    assert value['cameras'][0]['status']=='stopped'
    assert 'processing_fps' not in value['health']


def test_connected_pairing_preserves_hosted_endpoint_and_transport_settings(window, monkeypatch):
    from sentinal.connected.edge import EdgeConfig
    from sentinal.interface.connected_dialog import QFileDialog
    window.open_connected_settings()
    dialog=window._connected_dialog
    config=EdgeConfig('https://authorized.example','edge-example','a'*48,request_timeout_s=7,max_attempts=3,ingest_path='/functions/ingest')
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:('paired.json',''))
    monkeypatch.setattr(EdgeConfig,'load',lambda *a,**k:config)
    dialog.load_config()
    assert dialog.config()==config
    assert dialog.config().endpoint=='https://authorized.example/functions/ingest'
    assert not dialog.enabled.isChecked()


def test_stopping_heartbeat_never_reports_active_inference(window):
    window.open_connected_settings()
    observed=[]
    window._edge_bridge._send_heartbeat=lambda:observed.append(window._connected_health())
    window._on_state('running','Started')
    window._on_state('stopped','Stopped')
    assert observed[-1]['health']=={'status':'idle'}
    assert 'processing_fps' not in observed[-1]['health']


@pytest.mark.parametrize('state,health',[('loading','reconnecting'),('reconnecting','reconnecting'),('paused','idle'),('eof','idle'),('error','error')])
def test_connected_health_preserves_nonprocessing_states(window,state,health):
    window._state=state;window._busy=True
    value=window._connected_health()['health']
    assert value=={'status':health}
    assert 'processing_fps' not in value
