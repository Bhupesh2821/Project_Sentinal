"""Setup UI contracts with fake device replies; no physical CCTV claim."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from sentinal.interface import network_camera_dialog as module
from sentinal.vision.network_discovery import NetworkCamera
from sentinal.vision.onvif_client import CameraStream


def spin(app,predicate,seconds=3):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        app.processEvents()
        if predicate():return
        time.sleep(.003)
    raise AssertionError('Setup UI transition timed out')


@pytest.fixture
def dialog():
    app=QApplication.instance() or QApplication([])
    view=module.NetworkCameraDialog();view.show();app.processEvents()
    yield app,view
    view.cancel_setup();view.wait_for_setup()
    for _ in range(5):app.processEvents()
    view.close();app.processEvents()


def test_profile_selection_requires_explicit_use_and_never_opens_video(dialog,monkeypatch):
    app,view=dialog;calls=[];selected=[]
    class Client:
        def __init__(self,address,username,password,**kwargs):calls.append((address,username,password))
        def list_streams(self):return [CameraStream('Main','rtsp://192.0.2.2:554/live','main',1280,720,'H264')]
    monkeypatch.setattr(module,'OnvifClient',Client)
    view.stream_selected.connect(lambda *args:selected.append(args))
    view.address.setText('http://192.0.2.2/onvif/device_service')
    view.username.setText('account');view.password.setText('UI-Only-Test-Secret')
    view.profiles_button.click()
    spin(app,lambda:not view.setup_running)
    assert calls==[('http://192.0.2.2/onvif/device_service','account','UI-Only-Test-Secret')]
    assert view.use_button.isEnabled() and not selected
    assert 'UI-Only-Test-Secret' not in view.status.text()+view.stream_hint.text()
    view.use_button.click();app.processEvents()
    assert selected==[('rtsp://192.0.2.2:554/live','account','UI-Only-Test-Secret')]
    assert not view.password.text() and not view._streams


def test_discovery_runs_only_on_click_and_does_not_get_streams(dialog,monkeypatch):
    app,view=dialog;calls=[]
    monkeypatch.setattr(module,'discover_cameras',lambda **kwargs:calls.append(True) or [NetworkCamera('Test camera','http://192.0.2.2/onvif')])
    assert not calls and not view.setup_running
    view.discover_button.click();spin(app,lambda:not view.setup_running)
    assert calls==[True] and view.camera_list.count()==1
    assert not view.use_button.isEnabled()
    view.camera_list.setCurrentRow(0)
    assert view.address.text()=='http://192.0.2.2/onvif'


def test_address_change_clears_old_credentials_and_profiles(dialog):
    _,view=dialog
    view.address.setText('http://192.0.2.2/onvif');view.username.setText('account');view.password.setText('old-secret')
    view._profiles_loaded([CameraStream('Main','rtsp://192.0.2.2/live','main')])
    view.address.setText('http://192.0.2.3/onvif')
    assert not view.username.text() and not view.password.text() and not view._streams
    assert not view.use_button.isEnabled()


def test_close_waits_for_worker_cancels_and_emits_no_late_stream(dialog,monkeypatch):
    app,view=dialog;entered=threading.Event();cancelled=threading.Event();selected=[]
    def discover(**kwargs):
        entered.set()
        assert kwargs['cancel_event'].wait(2)
        cancelled.set()
        return [NetworkCamera('Late camera','http://192.0.2.2/onvif')]
    monkeypatch.setattr(module,'discover_cameras',discover)
    view.stream_selected.connect(lambda *args:selected.append(args))
    view.discover_button.click();spin(app,entered.is_set)
    assert view.setup_running
    view.close();spin(app,lambda:not view.setup_running and not view.isVisible())
    assert cancelled.is_set() and not selected and view.camera_list.count()==0


def test_unexpected_worker_error_is_curated_and_allows_retry(dialog,monkeypatch):
    app,view=dialog
    def fail(**kwargs):raise RuntimeError('SecretRawBackendBody')
    monkeypatch.setattr(module,'discover_cameras',fail)
    view.discover_button.click();spin(app,lambda:not view.setup_running)
    assert 'SecretRawBackendBody' not in view.status.text()
    assert 'could not complete' in view.status.text() and view.discover_button.isEnabled()


@pytest.fixture
def dashboard(monkeypatch):
    from PySide6.QtCore import QObject, Signal, QTimer
    from sentinal.interface import main_window
    from sentinal.config import AppConfig
    class Worker(QObject):
        state_changed=Signal(str,str)
        error=Signal(str)
        metadata_failed=Signal(str)
        finished=Signal()
        playback_changed=Signal(object)
        def __init__(self,config,parent=None):
            super().__init__(parent);self.running=False;self.starts=[]
        def start(self):self.running=True
        def isRunning(self):return self.running
        def request_start(self,spec):self.starts.append(spec)
        def request_shutdown(self):
            def finish():self.running=False;self.finished.emit()
            QTimer.singleShot(0,finish)
        def set_options(self,**kwargs):pass
        def take_latest(self):return None
    class Library:
        def list_entries(self):return []
    monkeypatch.setattr(main_window,'InferenceWorker',Worker)
    monkeypatch.setattr(main_window,'VideoLibrary',Library)
    monkeypatch.setattr(main_window,'discover_cameras',lambda:[])
    app=QApplication.instance() or QApplication([])
    window=main_window.MainWindow(AppConfig());window.show();app.processEvents()
    yield app,window
    window.close()
    spin(app,lambda:not window.worker.isRunning())
    for _ in range(5):app.processEvents()


def test_selected_setup_stream_fills_dashboard_without_auto_start(dashboard):
    app,window=dashboard
    window.source_type.setCurrentIndex(2);window.open_network_setup()
    dialog=window._network_dialog
    dialog.stream_selected.emit('rtsp://192.0.2.2:554/live?token=test-only','account','TestOnly-Password')
    app.processEvents()
    assert window.source_type.currentIndex()==2
    assert window.stream_url.text()=='rtsp://192.0.2.2:554/live?token=test-only'
    assert window.stream_username.text()=='account' and window.stream_password.text()=='TestOnly-Password'
    assert not window.worker.starts and not window._busy
    assert 'Start monitoring' in window.stream_note.text()
    assert not window.metadata_toggle.isChecked()
    dialog.close()


def test_parent_close_waits_for_running_setup_worker(dashboard,monkeypatch):
    app,window=dashboard;entered=threading.Event();cancelled=threading.Event()
    def discover(**kwargs):
        entered.set();assert kwargs['cancel_event'].wait(2);cancelled.set();return []
    monkeypatch.setattr(module,'discover_cameras',discover)
    window.source_type.setCurrentIndex(2);window.open_network_setup()
    dialog=window._network_dialog;dialog.discover_button.click();spin(app,entered.is_set)
    window.close()
    spin(app,lambda:not window.worker.isRunning() and not dialog.setup_running and not window.isVisible())
    assert cancelled.is_set() and not window.worker.starts
