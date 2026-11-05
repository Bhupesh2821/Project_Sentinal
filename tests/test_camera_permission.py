"""Fake permission states and fake capture workers; no OS prompt or camera proof."""
from types import SimpleNamespace
import time
import pytest
from PySide6.QtCore import QObject,Signal,QTimer,Qt
from PySide6.QtWidgets import QApplication
from sentinal.interface.camera_permission import CameraPermissionGate,QtCameraPermissionBackend
from sentinal.interface import main_window,camera_wall
from sentinal.config import AppConfig
from sentinal.core.v02_settings import V02Settings
from sentinal.vision.camera_manager import CameraInfo
from sentinal.storage.camera_registry import CameraRegistry

GRANTED=Qt.PermissionStatus.Granted
DENIED=Qt.PermissionStatus.Denied
UNKNOWN=Qt.PermissionStatus.Undetermined

class Backend:
    def __init__(self,status=UNKNOWN):self.status=status;self.checks=0;self.requests=[]
    def check(self):self.checks+=1;return self.status
    def request(self,context,callback):self.requests.append(callback)
    def reply(self,status=GRANTED):self.status=status;self.requests[-1](SimpleNamespace(status=lambda:status))


def test_gate_constructs_without_checking_or_requesting_os_permission():
    backend=Backend();gate=CameraPermissionGate(backend=backend)
    assert not gate.pending and backend.checks==0 and backend.requests==[]


def test_granted_permission_runs_only_supplied_intent_without_request():
    backend=Backend(GRANTED);gate=CameraPermissionGate(backend=backend);calls=[]
    assert gate.ensure(object(),lambda:calls.append('exact-camera'))
    assert calls==['exact-camera'] and backend.requests==[] and not gate.pending


def test_unknown_permission_is_one_request_and_one_continuation():
    backend=Backend();gate=CameraPermissionGate(backend=backend);owner=object();calls=[]
    gate.ensure(owner,lambda:calls.append('first'))
    gate.ensure(object(),lambda:calls.append('competing'))
    assert gate.pending_for(owner) and len(backend.requests)==1 and not calls
    backend.reply()
    assert calls==['first'] and not gate.pending


@pytest.mark.parametrize('cancel',['stop','source-change','close'])
def test_cancelled_intent_cannot_start_after_late_permission_grant(cancel):
    backend=Backend();gate=CameraPermissionGate(backend=backend);calls=[]
    gate.ensure(object(),lambda:calls.append(cancel));gate.cancel();backend.reply()
    assert not calls and not gate.pending


def test_denied_permission_never_starts_and_explains_system_settings():
    backend=Backend(DENIED);gate=CameraPermissionGate(backend=backend);calls=[];errors=[]
    gate.error.connect(errors.append);gate.ensure(object(),lambda:calls.append('capture'))
    assert not calls and not backend.requests
    assert 'Privacy & Security' in errors[-1] and 'No camera was opened' in errors[-1]


def test_denial_after_prompt_never_starts_or_reprompts():
    backend=Backend();gate=CameraPermissionGate(backend=backend);calls=[];errors=[]
    gate.error.connect(errors.append);gate.ensure(object(),lambda:calls.append('capture'));backend.reply(DENIED)
    assert not calls and errors and len(backend.requests)==1 and not gate.pending


def test_cancel_keeps_native_inflight_request_bounded_until_it_finishes():
    backend=Backend();gate=CameraPermissionGate(backend=backend);calls=[]
    gate.ensure(object(),lambda:calls.append('old'));gate.cancel()
    gate.ensure(object(),lambda:calls.append('new-too-early'))
    assert len(backend.requests)==1 and not gate.pending
    backend.reply();gate.ensure(object(),lambda:calls.append('new-explicit-start'))
    assert calls==['new-explicit-start']


def test_pending_release_callback_cannot_restart_cancelled_owner():
    backend=Backend();gate=CameraPermissionGate(backend=backend);owner=object();calls=[]
    gate.pending_changed.connect(lambda pending:None if pending else gate.cancel(owner))
    gate.ensure(owner,lambda:calls.append('old'));backend.reply()
    assert calls==[]


def test_backend_failure_is_safe_and_does_not_leave_pending_intent():
    backend=Backend();gate=CameraPermissionGate(backend=backend);calls=[];errors=[]
    gate.error.connect(errors.append)
    def fail(*_):raise RuntimeError('Private driver detail')
    backend.request=fail;gate.ensure(object(),lambda:calls.append('capture'))
    assert not calls and not gate.pending and 'Private driver detail' not in errors[-1]


class SingleWorker(QObject):
    state_changed=Signal(str,str);error=Signal(str);metadata_failed=Signal(str);finished=Signal();playback_changed=Signal(object)
    def __init__(self,*args):super().__init__();self.running=False;self.starts=[]
    def start(self):self.running=True
    def isRunning(self):return self.running
    def request_start(self,spec):self.starts.append(spec);self.state_changed.emit('running','Unit source only')
    def request_stop(self):self.state_changed.emit('stopped','Unit source stopped')
    def request_shutdown(self):self.running=False;QTimer.singleShot(0,self.finished.emit)
    def set_options(self,**kwargs):pass
    def set_hazard_options(self,**kwargs):pass
    def set_incident_consumer(self,consumer):pass
    def take_latest(self):return None

class WallWorker(QObject):
    state_changed=Signal(str,str,str);error=Signal(str,str);finished=Signal()
    def __init__(self,*a,**k):super().__init__();self.running=False;self.starts=[];self.is_monitoring=False
    def start(self):self.running=True
    def isRunning(self):return self.running
    def request_start(self,selections):self.starts.append(tuple(selections));self.is_monitoring=True;return True
    def request_stop(self,*_):self.is_monitoring=False;return True
    def request_shutdown(self):self.running=False;QTimer.singleShot(0,self.finished.emit)
    def set_options(self,**kwargs):pass
    def set_incident_consumer(self,consumer):pass
    def take_latest(self):return {}

@pytest.fixture
def view(monkeypatch,tmp_path):
    app=QApplication.instance() or QApplication([]);backend=Backend()
    devices=[CameraInfo(0,'MacBook camera','aabb'),CameraInfo(1,'iPhone camera','ccdd')]
    monkeypatch.setattr(main_window,'CameraPermissionGate',lambda parent:CameraPermissionGate(parent,backend))
    monkeypatch.setattr(main_window,'InferenceWorker',SingleWorker)
    monkeypatch.setattr(camera_wall,'MultiCameraWorker',WallWorker)
    monkeypatch.setattr(main_window,'discover_cameras',lambda:list(devices))
    monkeypatch.setattr('sentinal.vision.camera_manager.discover_cameras',lambda:list(devices))
    monkeypatch.setattr(main_window,'VideoLibrary',lambda:SimpleNamespace(list_entries=lambda:[]))
    monkeypatch.setattr(V02Settings,'load',classmethod(lambda cls:cls()))
    parent=main_window.MainWindow(AppConfig());parent.show();app.processEvents()
    registry=CameraRegistry(tmp_path/'cameras.sqlite3');parent._camera_registry=registry
    yield app,parent,backend,devices,registry
    parent.close();deadline=time.monotonic()+3
    while parent.isVisible() and time.monotonic()<deadline:app.processEvents();time.sleep(.003)
    assert not parent.isVisible()


def test_window_startup_and_passive_refresh_do_not_request_permission(view):
    _,parent,backend,_,_=view
    parent.refresh_cameras()
    assert backend.checks==0 and backend.requests==[] and parent.worker.starts==[]


def test_single_local_camera_waits_then_uses_exact_original_identity(view):
    _,parent,backend,_,_=view
    parent.camera_combo.setCurrentIndex(2);parent.start_button.click()
    assert not parent.worker.starts and len(backend.requests)==1
    assert not parent.start_button.isEnabled() and parent.stop_button.isEnabled()
    backend.reply();assert parent.worker.starts[0].camera_device_id=='ccdd'


@pytest.mark.parametrize('action',['stop','source','device','close'])
def test_single_pending_camera_start_is_cancelled_by_user_change(view,action):
    app,parent,backend,_,_=view;parent.start_monitoring()
    if action=='stop':parent.stop_button.click()
    elif action=='source':parent.source_type.setCurrentIndex(1)
    elif action=='device':parent.camera_combo.setCurrentIndex(2)
    else:parent.close();app.processEvents()
    backend.reply();assert parent.worker.starts==[]


def test_unavailable_exact_camera_is_not_replaced_after_grant(view):
    _,parent,backend,devices,_=view;parent.start_monitoring();devices[:]=[devices[1]]
    backend.reply();assert parent.worker.starts==[]
    assert parent.camera_combo.currentData() is None


def test_no_device_permission_flow_refreshes_and_requires_selection_and_start(view):
    _,parent,backend,devices,_=view;devices.clear();parent._selected_camera_id=None;parent.refresh_cameras()
    parent.start_monitoring();assert len(backend.requests)==1 and not parent.worker.starts
    devices.append(CameraInfo(0,'iPhone camera','ccdd'));backend.reply()
    assert parent.camera_combo.currentData() is None and not parent.worker.starts
    assert 'Select the exact camera' in parent.connection_label.text()


@pytest.mark.parametrize('kind',['file','stream'])
def test_file_and_rtsp_never_check_or_request_local_camera_permission(view,kind):
    _,parent,backend,_,_=view
    if kind=='file':parent.load_video('tests/fixtures/vtest.avi')
    else:parent.source_type.setCurrentIndex(2);parent.stream_url.setText('rtsp://127.0.0.1:18554/test')
    parent.start_monitoring()
    assert len(parent.worker.starts)==1 and parent.worker.starts[0].kind==kind
    assert backend.checks==0 and not backend.requests


def local_wall(parent,registry):
    camera=registry.upsert_local('Explicit Mac','aabb')
    stream=registry.upsert_network('Authorized test stream','rtsp://127.0.0.1:18554/test')
    selections=(registry.resolve(camera.camera_id),registry.resolve(stream.camera_id))
    parent.open_camera_wall();wall=parent._camera_wall;wall.set_selections(selections)
    return wall,selections


def test_wall_local_camera_waits_for_one_shared_permission_then_exact_group(view):
    _,parent,backend,_,registry=view;wall,selections=local_wall(parent,registry)
    expected=[wall.table.item(i,0).data(Qt.ItemDataRole.UserRole) for i in range(wall.table.rowCount()) if wall.table.item(i,0).checkState()==Qt.CheckState.Checked]
    wall.start_button.click();assert parent._camera_permission.pending and not wall.is_monitoring and not wall.worker.starts and len(backend.requests)==1
    assert wall.stop_all.isEnabled() and 'PERMISSION' in parent.status_chip.text()
    parent.start_monitoring()
    assert not parent.worker.starts and not wall.worker.starts
    backend.reply();assert len(wall.worker.starts)==1
    assert [item.record.camera_id for item in wall.worker.starts[0]]==expected
    assert set(expected)=={item.record.camera_id for item in selections}


@pytest.mark.parametrize('action',['stop','selection','close'])
def test_wall_cancelled_selection_cannot_start_after_permission_reply(view,action):
    app,parent,backend,_,registry=view;wall,_=local_wall(parent,registry);wall.start_button.click()
    if action=='stop':wall.stop_all.click()
    elif action=='selection':wall.table.item(0,0).setCheckState(Qt.CheckState.Unchecked)
    else:wall.close();app.processEvents()
    backend.reply();assert not wall.worker.starts


def test_single_pending_intent_blocks_competing_wall_start(view):
    _,parent,backend,_,registry=view;wall,_=local_wall(parent,registry)
    parent.start_monitoring();wall.start_checked()
    assert len(backend.requests)==1 and not wall.worker.starts
    backend.reply();assert len(parent.worker.starts)==1 and not wall.worker.starts


@pytest.mark.parametrize('initial',[GRANTED,UNKNOWN])
def test_permission_continuation_error_is_safe_and_visible(initial):
    backend=Backend(initial);gate=CameraPermissionGate(backend=backend);errors=[]
    gate.error.connect(errors.append)
    def fail():raise RuntimeError('rtsp://account:private@internal.example/feed')
    gate.ensure(object(),fail)
    if initial==UNKNOWN:backend.reply()
    assert errors and 'Stop before retrying' in errors[-1]
    assert 'rtsp://' not in errors[-1] and 'private' not in errors[-1]
    assert not gate.pending


def test_wall_denied_permission_has_visible_guidance_in_its_own_dialog(view):
    _,parent,backend,_,registry=view;backend.status=DENIED;wall,_=local_wall(parent,registry)
    wall.start_button.click()
    assert not wall.worker.starts and 'Privacy & Security' in wall.message.text()
    assert not wall.stop_all.isEnabled()


def test_existing_tile_stop_invalidates_pending_expanded_wall_group(view):
    _,parent,backend,_,registry=view;wall,selections=local_wall(parent,registry)
    wall.start_selections((selections[1],))
    assert len(wall.worker.starts)==1
    wall.start_selections(selections)
    assert len(backend.requests)==1 and parent._camera_permission.pending
    wall.tiles[selections[1].record.camera_id].stop_button.click()
    backend.reply()
    assert len(wall.worker.starts)==1


def test_new_video_intent_cancels_waiting_wall_start(view):
    _,parent,backend,_,registry=view;wall,_=local_wall(parent,registry);wall.start_button.click()
    parent.load_video('tests/fixtures/vtest.avi');parent.start_monitoring();backend.reply()
    assert len(parent.worker.starts)==1 and parent.worker.starts[0].kind=='file'
    assert not wall.worker.starts



def test_permission_backend_requires_actual_gui_thread_without_requesting_os():
    import threading
    app=QApplication.instance() or QApplication([]);backend=QtCameraPermissionBackend();errors=[]
    assert backend._app() is app
    def off_thread():
        try:backend._app()
        except RuntimeError as exc:errors.append(str(exc))
    thread=threading.Thread(target=off_thread);thread.start();thread.join(timeout=2)
    assert not thread.is_alive() and errors==['Camera consent requires the application GUI thread']


def test_explicit_camera_refresh_requests_permission_but_never_starts_capture(view):
    _,parent,backend,_,_=view
    parent.refresh_button.click();assert len(backend.requests)==1 and not parent.worker.starts
    backend.reply();assert not parent.worker.starts and not parent._busy
    assert 'No camera was opened' in parent.connection_label.text()
