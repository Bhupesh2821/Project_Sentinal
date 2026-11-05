"""Camera management UI contracts; fake probes are not hardware evidence."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading,time
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from sentinal.interface import camera_manager_dialog as module
from sentinal.storage.camera_registry import CameraRegistry
from sentinal.vision.camera_manager import CameraInfo


def spin(app,predicate,seconds=3):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.processEvents()
        if predicate():return
        time.sleep(.004)
    raise AssertionError('Camera manager transition timed out')

@pytest.fixture
def view(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(module,'discover_cameras',lambda:[CameraInfo(1,'MacBook Air Camera','aabb'),CameraInfo(0,'iPhone Camera','ccdd')])
    registry=CameraRegistry(tmp_path/'private/registry.sqlite3')
    dialog=module.CameraManagerDialog(registry=registry);dialog.show();app.processEvents()
    yield app,dialog,registry
    dialog.cancel_setup();dialog.wait_for_setup()
    for _ in range(5):app.processEvents()
    dialog.close();app.processEvents();registry.close()

def add_network(dialog):
    dialog.name.setText('Entrance');dialog.endpoint.setText('rtsp://127.0.0.1:8554/private?token=LocalTest');dialog.username.setText('viewer');dialog.password.setText('ExampleSecret');dialog.save_button.click()

def test_save_and_use_are_explicit_and_do_not_start_capture(view,monkeypatch):
    app,dialog,registry=view;opened=[];selected=[]
    monkeypatch.setattr(module,'LiveVideoSource',lambda *a,**k:opened.append(a))
    dialog.camera_selected.connect(selected.append)
    assert not dialog.remember.isChecked() and not dialog.setup_running
    add_network(dialog)
    assert len(registry.list_cameras())==1 and dialog.table.rowCount()==1
    assert not opened and not selected
    dialog.use_button.click();app.processEvents()
    assert len(selected)==1 and selected[0].spec.kind=='stream'
    assert selected[0].password=='ExampleSecret' and not opened
    assert not dialog.password.text()
    assert b'ExampleSecret' not in registry.path.read_bytes()

def test_local_camera_must_be_chosen_and_missing_device_is_not_substituted(view):
    _,dialog,registry=view
    dialog.kind.setCurrentIndex(1);dialog.name.setText('Mac selected')
    dialog.save_button.click();assert not registry.list_cameras()
    dialog.local_camera.setCurrentIndex(1);dialog.save_button.click()
    record=registry.list_cameras()[0]
    assert registry.resolve(record.camera_id).spec.camera_device_id=='aabb'
    assert dialog.local_camera.currentData().device_id=='aabb'

def test_monitoring_disables_competing_probe_and_source_use(view):
    _,dialog,_=view;add_network(dialog)
    dialog.set_monitoring_active(True)
    assert not dialog.test_button.isEnabled() and not dialog.use_button.isEnabled()
    dialog.test_selected();assert not dialog.setup_running
    dialog.set_monitoring_active(False)
    assert dialog.test_button.isEnabled() and dialog.use_button.isEnabled()

def test_connection_test_reads_one_frame_releases_and_records_actual_time(view,monkeypatch):
    app,dialog,registry=view;instances=[]
    class Source:
        def __init__(self,*a,**k):self.capture=object();self.reads=0;instances.append(self)
        def open(self):pass
        def read(self):self.reads+=1;return np.zeros((48,64,3),dtype=np.uint8)
        def close(self):self.capture=None
    monkeypatch.setattr(module,'LiveVideoSource',Source)
    add_network(dialog);dialog.test_button.click()
    spin(app,lambda:not dialog.setup_running)
    assert instances[0].reads==1 and instances[0].capture is None
    record=registry.list_cameras()[0]
    assert record.last_frame_utc and record.connection_health=='stopped'
    assert record.ai_status=='idle' and record.authentication_status=='authenticated'
    assert 'then released' in dialog.status.text()
    assert not list(registry.path.parent.glob('*.jpg'))

def test_close_cancels_pending_probe_waits_and_can_reopen(view,monkeypatch):
    app,dialog,registry=view;entered=threading.Event();release=threading.Event();closed=[]
    class Source:
        def __init__(self,*a,**k):self.capture=object()
        def open(self):entered.set();assert release.wait(2)
        def read(self):raise AssertionError('Cancelled probe must not read')
        def close(self):self.capture=None;closed.append(True)
    monkeypatch.setattr(module,'LiveVideoSource',Source)
    add_network(dialog);dialog.test_button.click();spin(app,entered.is_set)
    dialog.close();assert dialog.setup_running and dialog.isVisible()
    release.set();spin(app,lambda:not dialog.setup_running and not dialog.isVisible())
    assert closed and registry.list_cameras()[0].connection_health=='stopped'
    dialog.show();app.processEvents()
    assert dialog.save_button.isEnabled()

def test_onvif_profile_only_fills_fields_until_save_and_use(view):
    _,dialog,registry=view
    dialog._on_onvif('rtsp://127.0.0.1/from-profile','viewer','PrivateTest')
    assert dialog.endpoint.text().endswith('from-profile')
    assert not registry.list_cameras() and not dialog.setup_running
    assert 'No video connection' in dialog.status.text()
