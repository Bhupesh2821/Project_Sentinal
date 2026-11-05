"""Camera-wall UI contracts with explicit fake workers, not hardware/AI proof."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtCore import QObject,Signal,QTimer,Qt
from PySide6.QtWidgets import QApplication
from sentinal.config import AppConfig
from sentinal.core.v02_settings import V02Settings
from sentinal.interface import camera_wall,main_window
from sentinal.storage.camera_registry import CameraRegistry
from sentinal.vision.types import FramePacket,Detection,utc_now
from sentinal.vision.specialized import HazardObservation


class SingleWorker(QObject):
    state_changed=Signal(str,str);error=Signal(str);metadata_failed=Signal(str);finished=Signal();playback_changed=Signal(object)
    def __init__(self,config,parent=None):super().__init__(parent);self.running=False;self.starts=[]
    def start(self):self.running=True
    def isRunning(self):return self.running
    def request_start(self,spec):self.starts.append(spec)
    def request_shutdown(self):
        def done():self.running=False;self.finished.emit()
        QTimer.singleShot(0,done)
    def request_stop(self):self.state_changed.emit('stopped','Unit test source stopped')
    def set_options(self,**kwargs):pass
    def set_hazard_options(self,**kwargs):pass
    def set_incident_consumer(self,consumer):pass
    def take_latest(self):return None


class MultiWorker(QObject):
    state_changed=Signal(str,str,str);error=Signal(str,str);finished=Signal()
    def __init__(self,config,parent=None,max_cameras=8,**kwargs):
        super().__init__(parent);self.running=False;self.starts=[];self.stop_requests=[];self.shutdown_requested=False
        self.options={};self.consumer=None;self.latest={};self.source_states={};self.selected=()
    def start(self):self.running=True
    def isRunning(self):return self.running
    @property
    def is_monitoring(self):return any(state in {'loading','running','reconnecting','stopping'} for state in self.source_states.values())
    def request_start(self,selections):self.selected=tuple(selections);self.starts.append(tuple(selections));return True
    def emit_state(self,ident,state,message='Unit test source state'):
        self.source_states[ident]=state;self.state_changed.emit(ident,state,message)
    def request_stop(self,ident=None):
        self.stop_requests.append(ident)
        targets=[selection.record.camera_id for selection in self.selected if ident is None or ident==selection.record.camera_id]
        for source in targets:
            self.emit_state(source,'stopping');QTimer.singleShot(0,lambda s=source:self.emit_state(s,'stopped'))
        return True
    def request_shutdown(self):
        if self.shutdown_requested:return
        self.shutdown_requested=True
        def done():
            for source in list(self.source_states):self.emit_state(source,'stopped')
            self.running=False;self.finished.emit()
        QTimer.singleShot(0,done)
    def set_options(self,**kwargs):self.options.update(kwargs)
    def set_incident_consumer(self,consumer):self.consumer=consumer
    def take_latest(self):result,self.latest=self.latest,{};return result


def spin(app,predicate,timeout=3):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        app.processEvents()
        if predicate():return
        time.sleep(.004)
    raise AssertionError('Camera-wall UI transition timed out')


@pytest.fixture
def wall_view(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window,'InferenceWorker',SingleWorker)
    monkeypatch.setattr(camera_wall,'MultiCameraWorker',MultiWorker)
    monkeypatch.setattr(main_window,'discover_cameras',lambda:[])
    monkeypatch.setattr(main_window,'VideoLibrary',lambda:SimpleNamespace(list_entries=lambda:[]))
    monkeypatch.setattr(V02Settings,'load',classmethod(lambda cls:cls()))
    parent=main_window.MainWindow(AppConfig());parent.show();app.processEvents()
    registry=CameraRegistry(tmp_path/'camera-wall/registry.sqlite3');parent._camera_registry=registry
    first=registry.upsert_network('Door','rtsp://127.0.0.1:18554/door')
    second=registry.upsert_network('Hall','rtsp://127.0.0.1:18554/hall')
    selections=(registry.resolve(first.camera_id),registry.resolve(second.camera_id))
    parent.open_camera_wall();wall=parent._camera_wall;app.processEvents()
    yield app,parent,wall,registry,selections
    parent.close();spin(app,lambda:not parent.isVisible() and not parent.worker.isRunning() and not wall.worker.isRunning())


def packet(index=1):
    return FramePacket(np.zeros((120,160,3),np.uint8),(Detection(0,'person',.9,(5,5,45,100),1),),
        'unit-wall-session','Unit fixture',index,utc_now(),index*.2,8.,22.,23.,'cpu',frame_age_ms=35.,dropped_frames=2,
        model_name='unit-only.pt',hazards=(HazardObservation('fire',.82,(55,35,115,95),1,'unit-detector','1','fire_smoke'),),hazard_sampled=True)


def start_pair(wall,selections):
    wall.set_selections(selections);wall.start_button.click()
    for selection in selections:wall.worker.emit_state(selection.record.camera_id,'running')


def test_wall_opens_in_standby_and_selection_does_not_capture(wall_view):
    _,parent,wall,_,selections=wall_view
    assert wall.worker.isRunning() and not wall.is_monitoring and not wall.worker.starts
    assert not wall.hazards.isChecked() and not wall.record.isChecked() and not wall.evidence.isChecked()
    assert not parent.worker.starts
    wall.set_selections(selections)
    assert not wall.worker.starts and not wall.tiles
    assert all(wall.table.item(i,0).checkState()==Qt.CheckState.Checked for i in range(2))


def test_explicit_start_uses_only_checked_camera_ids(wall_view):
    _,parent,wall,_,selections=wall_view
    wall.set_selections(selections);wall.table.item(1,0).setCheckState(Qt.CheckState.Unchecked)
    wall.start_button.click()
    assert len(wall.worker.starts)==1 and len(wall.worker.starts[0])==1
    assert wall.worker.starts[0][0].record.camera_id==wall.table.item(0,0).data(Qt.ItemDataRole.UserRole)
    assert not parent.worker.starts


def test_pending_wall_start_blocks_competing_single_source(wall_view):
    _,parent,wall,_,selections=wall_view
    wall.set_selections(selections);wall.start_button.click()
    assert wall.is_monitoring,'Queued sources must reserve the wall before worker acknowledgment'
    assert not parent.start_button.isEnabled()
    parent.load_video('tests/fixtures/vtest.avi');parent.start_monitoring()
    assert not parent.worker.starts


def test_source_error_clears_only_its_tile_and_preserves_other_feed(wall_view):
    _,_,wall,_,selections=wall_view;start_pair(wall,selections)
    first,second=[s.record.camera_id for s in selections]
    wall.worker.latest={first:packet(),second:packet(2)};wall._poll()
    wall.worker.emit_state(first,'error','Unit fixture unavailable')
    assert wall.tiles[first].last_packet is None and 'No active inference' in wall.tiles[first].metrics.text()
    assert wall.tiles[second].last_packet.frame_index==2 and wall.states[second]=='running'
    wall.worker.latest={first:packet(3),second:packet(4)};wall._poll()
    assert wall.tiles[first].last_packet is None and wall.tiles[second].last_packet.frame_index==4
    assert wall.is_monitoring


def test_per_feed_stop_does_not_stop_the_other_camera(wall_view):
    app,_,wall,_,selections=wall_view;start_pair(wall,selections)
    first,second=[s.record.camera_id for s in selections]
    wall.tiles[first].stop_button.click();spin(app,lambda:wall.states[first]=='stopped')
    assert wall.worker.stop_requests==[first]
    assert wall.states[second]=='running' and wall.is_monitoring


def test_packets_render_per_feed_measured_metrics_and_annotations(wall_view):
    app,parent,wall,_,selections=wall_view;start_pair(wall,selections)
    ident=selections[0].record.camera_id
    parent.boxes_toggle.setChecked(False);parent.labels_toggle.setChecked(True);parent.ids_toggle.setChecked(False)
    sample=packet();wall.worker.latest={ident:sample};wall._poll();app.processEvents()
    tile=wall.tiles[ident]
    assert tile.last_packet is sample and tile.video._packet is sample
    assert '8.0' in tile.metrics.text() and '22' in tile.metrics.text() and sample.timestamp in tile.metrics.text()
    assert not tile.video.show_boxes and tile.video.show_labels and not tile.video.show_ids
    assert not sample.frame.any()


def test_close_wall_is_async_and_releases_all_sources(wall_view):
    app,_,wall,_,selections=wall_view;start_pair(wall,selections)
    wall.close()
    assert wall.worker.shutdown_requested and wall.setup_running
    spin(app,lambda:wall._closed and not wall.worker.isRunning())
    assert all(value=='stopped' for value in wall.states.values())


def test_parent_close_waits_for_wall_and_incident_worker(wall_view):
    app,parent,wall,_,selections=wall_view
    parent.hazards_toggle.setChecked(True);service=parent._incident_worker
    start_pair(wall,selections);parent.close()
    assert parent._closing and wall.worker.shutdown_requested
    spin(app,lambda:not parent.isVisible() and not wall.worker.isRunning() and not service.isRunning())
    assert parent._camera_registry is None


def test_checked_selection_rejects_missing_session_credentials_without_start(wall_view):
    _,_,wall,registry,selections=wall_view;wall.set_selections(selections)
    registry.credentials.clear_session();wall.start_button.click()
    assert not wall.worker.starts and 'Could not start' in wall.message.text()


def test_wall_options_include_the_selected_object_model(wall_view):
    _,parent,wall,_,_=wall_view
    index=parent.model_combo.findData('models/yolov8n-oiv7.pt')
    parent.model_combo.setCurrentIndex(index);wall.apply_options()
    assert wall.worker.options.get('model_path')=='models/yolov8n-oiv7.pt'


def incident_row(source_id,status='ALERTED',ident='wall-review-incident'):
    stamp=utc_now()
    return {'incident_id':ident,'source_id':source_id,'session_id':'unit-wall-session',
        'category':'fire','status':status,'confidence':.82,'severity':3,
        'model_id':'unit-detector','model_version':'unit-only',
        'bbox':(55.,35.,115.,95.),'track_id':1,'first_seen':stamp,'last_seen':stamp,
        'alerted_at':stamp,'alert_latency_ms':400.,'persistence_status':'session_only'}


def test_pending_wall_start_locks_model_until_all_cameras_stop(wall_view):
    app,parent,wall,_,selections=wall_view
    wall.set_selections(selections);wall.start_button.click()
    assert not parent.model_combo.isEnabled()
    for selection in selections:wall.worker.emit_state(selection.record.camera_id,'running')
    wall.tiles[selections[0].record.camera_id].stop_button.click()
    spin(app,lambda:wall.states[selections[0].record.camera_id]=='stopped')
    assert not parent.model_combo.isEnabled()
    wall.stop_all.click();spin(app,lambda:not wall.is_monitoring)
    wall._poll()
    assert parent.model_combo.isEnabled() and parent.start_button.isEnabled()


def test_actual_packet_timestamp_updates_camera_health_only_when_fresh(wall_view):
    _,_,wall,registry,selections=wall_view;start_pair(wall,selections)
    first,second=[selection.record.camera_id for selection in selections]
    sample=packet();wall.worker.latest={first:sample};wall._poll()
    assert registry.get(first).last_frame_utc==sample.timestamp
    assert registry.get(first).connection_health=='online' and registry.get(first).ai_status=='active'
    assert registry.get(second).last_frame_utc is None
    wall.worker.emit_state(first,'error','Unit stream lost')
    wall.worker.latest={first:packet(2)};wall._poll()
    assert registry.get(first).last_frame_utc==sample.timestamp
    assert registry.get(first).connection_health=='error' and registry.get(first).ai_status=='error'


def test_alert_is_visible_on_its_camera_and_reviews_update_same_incident(wall_view):
    app,parent,wall,_,selections=wall_view
    parent.hazards_toggle.setChecked(True);start_pair(wall,selections)
    first,second=[selection.record.camera_id for selection in selections]
    parent._incident_worker.incident_changed.emit(incident_row(first))
    app.processEvents()
    assert 'POSSIBLE' in wall.alert_summary.text() and 'FIRE' in wall.alert_summary.text()
    assert wall.tiles[first].alert.isVisible() and '82%' in wall.tiles[first].alert.text()
    assert 'Awaiting' in wall.tiles[first].alert.text()
    assert wall.tiles[first].incident_id=='wall-review-incident'
    assert 'POSSIBLE' not in wall.tiles[second].alert.text()
    parent._incident_worker.incident_changed.emit(incident_row(first,'ACKNOWLEDGED'));app.processEvents()
    assert 'ACKNOWLEDGED' in wall.tiles[first].alert.text()
    parent._incident_worker.incident_changed.emit(incident_row(first,'DISMISSED'));app.processEvents()
    assert 'DISMISSED' in wall.tiles[first].alert.text()
    assert not any(toggle.isChecked() for toggle in (parent.audio_toggle,parent.desktop_toggle,parent.incident_record_toggle,parent.evidence_toggle))


def test_other_incident_review_cannot_overwrite_latest_camera_alert(wall_view):
    app,parent,wall,_,selections=wall_view
    parent.hazards_toggle.setChecked(True);start_pair(wall,selections)
    first=selections[0].record.camera_id
    parent._incident_worker.incident_changed.emit(incident_row(first,ident='old-incident'))
    parent._incident_worker.incident_changed.emit(incident_row(first,ident='new-incident'))
    parent._incident_worker.incident_changed.emit(incident_row(first,'DISMISSED','old-incident'));app.processEvents()
    assert wall.tiles[first].incident_id=='new-incident' and 'Awaiting' in wall.tiles[first].alert.text()


def test_close_then_reopen_starts_empty_and_releases_selection_credentials(wall_view):
    app,parent,wall,_,selections=wall_view
    start_pair(wall,selections);wall.close();spin(app,lambda:wall._closed)
    assert not wall._selected and all(tile.last_packet is None for tile in wall.tiles.values())
    parent.open_camera_wall();fresh=parent._camera_wall;app.processEvents()
    assert fresh is not wall and fresh.worker.isRunning()
    assert not fresh.is_monitoring and not fresh.worker.starts and not fresh._selected and not fresh.tiles
    assert not parent.worker.starts
    fresh.close();spin(app,lambda:fresh._closed)


def test_rejected_start_does_not_create_ghost_loading_state(wall_view,monkeypatch):
    _,parent,wall,_,selections=wall_view
    monkeypatch.setattr(wall.worker,'request_start',lambda _:False)
    wall.set_selections(selections);wall.start_button.click()
    assert not wall.is_monitoring and not wall.tiles and not wall.states
    assert parent.start_button.isEnabled() and parent.model_combo.isEnabled()
    assert 'Could not start' in wall.message.text()


def test_adding_feed_keeps_existing_running_tile_and_frame(wall_view):
    _,_,wall,_,selections=wall_view
    first=selections[0].record.camera_id;second=selections[1].record.camera_id
    wall.start_selections(selections[:1]);wall.worker.emit_state(first,'running')
    sample=packet();wall.worker.latest={first:sample};wall._poll()
    tile=wall.tiles[first];wall.start_selections(selections)
    assert wall.states[first]=='running' and wall.tiles[first] is tile and tile.last_packet is sample
    assert wall.states[second]=='loading' and wall.tiles[second].last_packet is None


def test_wall_filter_controls_are_shared_without_starting_capture(wall_view):
    _,parent,wall,_,_=wall_view
    wall.filter_combo.setCurrentIndex(1);wall.apply_options()
    assert parent.filter_combo.currentIndex()==1 and wall.worker.options['category_filter']=='focus'
    parent.enable_all_detection()
    assert wall.filter_combo.currentIndex()==0 and wall.hazards.isChecked()
    assert not wall.worker.starts and not parent.worker.starts and not wall.is_monitoring
    assert not wall.record.isChecked() and not wall.evidence.isChecked()


def test_sampled_hazard_summary_reports_current_uncertainty_and_unavailable_models(wall_view):
    _,_,wall,_,selections=wall_view;start_pair(wall,selections)
    first=selections[0].record.camera_id
    sample=packet();wall.worker.latest={first:sample};wall._poll()
    assert 'POSSIBLE' in wall.tiles[first].observations.text() and '82%' in wall.tiles[first].observations.text()
    from dataclasses import replace
    missing=replace(sample,frame_index=2,hazards=(),detector_health={'weapons':{'status':'unavailable'}})
    wall.worker.latest={first:missing};wall._poll()
    assert 'No possible hazards' in wall.tiles[first].observations.text()
    assert 'Unavailable: weapons' in wall.tiles[first].observations.text()


def test_wall_keeps_exact_sampled_pixels_between_hazard_inference_frames(wall_view):
    from dataclasses import replace
    _,parent,wall,_,selections=wall_view
    parent.hazards_toggle.setChecked(True);start_pair(wall,selections)
    first=selections[0].record.camera_id
    health={'weapons':{'status':'active'}}
    analyzed=replace(packet(),frame=np.full((120,160,3),17,np.uint8),detector_health=health)
    newer=replace(packet(2),frame=np.full((120,160,3),93,np.uint8),hazards=(),hazard_sampled=False,detector_health=health)
    wall.worker.latest={first:analyzed};wall._poll()
    wall.worker.latest={first:newer};wall._poll()
    tile=wall.tiles[first]
    assert tile.last_packet is newer
    assert tile.video._packet is analyzed and tile.video._sampled_view
    assert (tile.video._packet.frame==17).all() and tile.video._packet.hazards
    parent.hazards_toggle.setChecked(False)
    wall.worker.latest={first:replace(newer,frame_index=3)};wall._poll()
    assert tile.video._packet.frame_index==3 and not tile.video._sampled_view
    assert not tile.video._packet.hazards and (tile.video._packet.frame==93).all()


def test_single_source_busy_locks_wall_model_including_immediate_reopen(wall_view):
    app,parent,wall,_,_=wall_view
    original=parent.model_combo.currentIndex();other=(original+1)%parent.model_combo.count()
    parent._set_busy(True);wall._poll()
    assert not parent.model_combo.isEnabled() and not wall.model_combo.isEnabled()
    wall.model_combo.setCurrentIndex(other)
    assert parent.model_combo.currentIndex()==original and wall.model_combo.currentIndex()==original
    wall.close();spin(app,lambda:wall._closed)
    parent.open_camera_wall();fresh=parent._camera_wall
    assert not fresh.model_combo.isEnabled(),'Single-source ownership must apply before the first timer poll'
    fresh.model_combo.setCurrentIndex(other)
    assert parent.model_combo.currentIndex()==original and fresh.model_combo.currentIndex()==original
    parent._set_busy(False);fresh._poll()
    assert fresh.model_combo.isEnabled()
    fresh.model_combo.setCurrentIndex(other)
    assert parent.model_combo.currentIndex()==other
    assert not fresh.worker.starts and not parent.worker.starts
    fresh.close();spin(app,lambda:fresh._closed)
