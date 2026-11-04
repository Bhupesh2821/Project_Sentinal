"""UI input contracts with explicit fakes; these are not camera/inference proof."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QTimer, Signal, QMimeData, QUrl
from PySide6.QtWidgets import QApplication, QLineEdit

from sentinal.config import AppConfig
from sentinal.interface import main_window


class Worker(QObject):
    state_changed = Signal(str, str)
    error = Signal(str)
    metadata_failed = Signal(str)
    finished = Signal()
    playback_changed = Signal(object)
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.running = False
        self.starts = []
        self.stops = 0
        self.seeks = []
        self.options = {}
    def start(self): self.running = True
    def isRunning(self): return self.running
    def request_start(self, spec):
        self.starts.append(spec)
        self.state_changed.emit("running", "Fake monitoring state")
        self.playback_changed.emit({"duration_s": 60, "position_s": 0, "can_seek": spec.kind == "file"})
    def request_stop(self):
        self.stops += 1
        self.state_changed.emit("stopped", "Fake source stopped")
    def request_pause(self, paused):
        self.state_changed.emit("paused" if paused else "running", "Fake pause state")
    def request_seek(self, seconds): self.seeks.append(seconds)
    def request_shutdown(self):
        def finish():
            self.running = False
            self.finished.emit()
        QTimer.singleShot(0, finish)
    def set_options(self, **kwargs): self.options.update(kwargs)
    def take_latest(self): return None


class Library:
    def __init__(self): self.entries = []
    def list_entries(self): return list(self.entries)


class Importer(QObject):
    progress = Signal(object, object)
    imported = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()
    def __init__(self, path, parent=None, library=None):
        super().__init__(parent)
        self.path, self.library = path, library
        self.cancel_requested = False
    def start(self): pass
    def cancel(self):
        self.cancel_requested = True
        QTimer.singleShot(0, self.complete_cancel)
    def complete_cancel(self):
        self.cancelled.emit(); self.finished.emit()
    def complete(self, path):
        entry = SimpleNamespace(path=Path(path), display_name=Path(path).name)
        self.library.entries = [entry]
        self.progress.emit(2 ** 33, 2 ** 33)
        self.imported.emit(entry)
        self.finished.emit()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch):
    monkeypatch.setattr(main_window, "InferenceWorker", Worker)
    monkeypatch.setattr(main_window, "VideoLibrary", Library)
    monkeypatch.setattr(main_window, "VideoImportWorker", Importer)
    monkeypatch.setattr(main_window, "discover_cameras", lambda: [])
    view = main_window.MainWindow(AppConfig())
    view.show(); app.processEvents()
    yield view
    view.close()
    for _ in range(5): app.processEvents()
    assert not view.worker.isRunning()


def test_dynamic_import_switches_running_source_without_restart(window, app):
    window.load_video("/explicit-ui-test/first.mp4")
    window.start_monitoring()
    original_worker = window.worker
    assert window.open_button.isEnabled(), "Import remains available while monitoring"
    window.begin_video_import("/explicit-ui-test/user-chosen.mp4")
    importer = window._import_worker
    assert window._state == "running"
    assert window.worker.stops == 0, "The old source continues while bytes import"
    importer.complete("/explicit-ui-test/managed-new.mp4")
    app.processEvents()
    assert window.worker is original_worker
    assert window.worker.stops == 1
    assert [Path(s.value).name for s in window.worker.starts] == ["first.mp4", "managed-new.mp4"]
    assert window._current_spec.kind == "file"
    assert window._state == "running"
    assert window._import_worker is None
    assert window.open_button.isEnabled()


def test_cancel_import_keeps_existing_source(window, app):
    window.load_video("/explicit-ui-test/current.mp4")
    window.start_monitoring()
    window.begin_video_import("/explicit-ui-test/large.mp4")
    importer = window._import_worker
    window.cancel_import(); app.processEvents()
    assert importer.cancel_requested
    assert window.worker.stops == 0
    assert len(window.worker.starts) == 1
    assert window._state == "running"
    assert window._import_worker is None


def test_import_failure_does_not_stop_monitoring(window, app):
    window.load_video("/explicit-ui-test/current.mp4")
    window.start_monitoring()
    window.begin_video_import("/explicit-ui-test/corrupted.mp4")
    importer = window._import_worker
    importer.failed.emit("This file could not be decoded.")
    importer.finished.emit(); app.processEvents()
    assert window.worker.stops == 0
    assert window._state == "running"
    assert "decoded" in window.error_banner.text()
    assert window.open_button.isEnabled()


def test_network_userinfo_is_masked_and_omitted_from_source_display(window):
    window.source_type.setCurrentIndex(2)
    window.stream_url.setText("rtsp://alice:ExampleSecret@127.0.0.1:8554/private?token=local")
    window.start_monitoring()
    assert len(window.worker.starts) == 1
    spec = window.worker.starts[0]
    assert spec.kind == "stream"
    assert "ExampleSecret" in spec.value, "Backend needs the ephemeral credential"
    assert "ExampleSecret" not in window.stream_url.text()
    assert window.stream_password.echoMode() == QLineEdit.EchoMode.Password
    assert "ExampleSecret" not in window.source_name.text()
    assert "private" not in window.source_name.text()
    assert "token" not in window.source_name.text()
    assert "ExampleSecret" not in repr(spec)
    assert not window.metadata_toggle.isChecked()


def test_missing_network_address_does_not_connect(window):
    window.source_type.setCurrentIndex(2)
    window.start_monitoring()
    assert not window.worker.starts
    assert "address" in window.error_banner.text()
    assert window.start_button.isEnabled()


def test_pause_resume_seek_and_runtime_resolution_controls(window):
    window.load_video("/explicit-ui-test/current.mp4")
    window.start_monitoring()
    assert window.pause_button.isEnabled()
    window.pause_button.click()
    assert window._state == "paused"
    assert window.pause_button.text() == "Resume"
    window.seek_slider.setValue(500)
    window._seek_released()
    assert window.worker.seeks == [30.0]
    window.pause_button.click()
    assert window._state == "running"
    window.resolution_combo.setCurrentIndex(window.resolution_combo.findData(320))
    assert window.worker.options["image_size"] == 320


class Drop:
    def __init__(self, urls):
        self.mime = QMimeData(); self.mime.setUrls(urls); self.accepted = False
    def mimeData(self): return self.mime
    def acceptProposedAction(self): self.accepted = True
    def ignore(self): self.accepted = False


def test_drop_imports_single_local_file_and_rejects_remote_url(window):
    remote = Drop([QUrl("https://example.invalid/movie.mp4")])
    window.dragEnterEvent(remote)
    assert not remote.accepted
    local = Drop([QUrl.fromLocalFile("/explicit-ui-test/a video.mov")])
    window.dragEnterEvent(local); assert local.accepted
    window.dropEvent(local)
    assert window._import_worker.path == "/explicit-ui-test/a video.mov"


def test_shutdown_cancels_pending_import_and_does_not_start_late_video(window, app):
    window.begin_video_import("/explicit-ui-test/large.mp4")
    importer = window._import_worker
    window.close(); app.processEvents(); app.processEvents()
    assert importer.cancel_requested
    assert not window.worker.starts
    assert not window.worker.isRunning()


def test_changing_camera_endpoint_does_not_reuse_its_password(window):
    window.stream_url.setText("rtsp://alice:FirstSecret@127.0.0.1:8554/stream")
    window._normalize_stream_fields()
    assert window.stream_password.text() == "FirstSecret"
    window.stream_url.setText("rtsp://192.0.2.2:8554/other")
    spec = window._stream_spec()
    assert window.stream_username.text() == ""
    assert window.stream_password.text() == ""
    assert "FirstSecret" not in spec.value
    assert "@" not in spec.value


def test_reconnect_clears_stale_live_detections(window):
    window.source_type.setCurrentIndex(2)
    window.stream_url.setText("http://127.0.0.1:8554/feed")
    window.start_monitoring()
    window.statistics.values["people"].setText("5")
    window.last_packet = object()
    window._on_state("reconnecting", "Feed interrupted · reconnecting…")
    assert window.last_packet is None
    assert window.statistics.values["people"].text() == "—"
    assert "fresh" in window.frame_label.text()
    assert window.video_panel.message == "RECONNECTING TO SOURCE"


def test_unexpected_worker_exit_disables_actions_that_cannot_run(window):
    window.worker.running = False
    window.worker.finished.emit()
    assert not window.start_button.isEnabled()
    assert not window.open_button.isEnabled()
    assert not window.library_combo.isEnabled()
    window.start_monitoring()
    assert not window.worker.starts
    assert "worker" in window.error_banner.text()


def test_exact_camera_choice_survives_reorder_and_never_substitutes(window, monkeypatch):
    from sentinal.vision.camera_manager import CameraInfo
    mac = CameraInfo(1, "MacBook Air Camera", "aabb", False)
    phone = CameraInfo(0, "iPhone Camera", "ccdd", True)
    monkeypatch.setattr(main_window, "discover_cameras", lambda: [phone, mac])
    window._camera_initialized = False
    window.refresh_cameras()
    assert window.camera_combo.currentData().device_id == "aabb", "System-default phone must not override built-in initial choice"
    window.camera_combo.setCurrentIndex(1)
    assert window.camera_combo.currentData().device_id == "ccdd"
    monkeypatch.setattr(main_window, "discover_cameras", lambda: [CameraInfo(0, mac.name, "aabb"), CameraInfo(1, phone.name, "ccdd")])
    window.refresh_cameras()
    assert window.camera_combo.currentData().device_id == "ccdd"
    window.start_monitoring()
    assert window.worker.starts[-1].camera_device_id == "ccdd"
    window.stop_monitoring()
    monkeypatch.setattr(main_window, "discover_cameras", lambda: [mac])
    window.refresh_cameras()
    assert window.camera_combo.currentData() is None
    count = len(window.worker.starts)
    window.start_monitoring()
    assert len(window.worker.starts) == count
    assert "Select the exact camera" in window.error_banner.text()


def test_no_camera_never_opens_an_unnamed_default(window):
    assert window.camera_combo.currentData() is None
    window.start_monitoring()
    assert not window.worker.starts
    assert "Select the exact camera" in window.error_banner.text()


def test_network_setup_selection_requires_explicit_monitoring_start(window):
    window._use_network_stream("rtsp://127.0.0.1:8554/returned", "viewer", "TransientSecret")
    assert not window.worker.starts
    assert window.source_type.currentIndex() == 2
    assert window.stream_password.text() == "TransientSecret"
    window.start_monitoring()
    assert len(window.worker.starts) == 1
    assert "TransientSecret" not in window.source_name.text()


def test_expanded_model_and_safety_filter_are_explicit_and_model_locks_while_running(window):
    window.model_combo.setCurrentIndex(1)
    window.filter_combo.setCurrentIndex(2)
    assert window.worker.options["model_path"] == "models/yolov8n-oiv7.pt"
    assert window.worker.options["category_filter"] == "safety"
    assert "577" in window.model_note.text()
    window.load_video("/explicit-ui-test/current.mp4")
    window.start_monitoring()
    assert not window.model_combo.isEnabled()
    window.stop_monitoring()
    assert window.model_combo.isEnabled()


def test_higher_capacity_model_is_explicit_and_shares_verified_catalog(window):
    index = window.model_combo.findData("models/yolov8s-oiv7.pt")
    assert index >= 0
    window.model_combo.setCurrentIndex(index)
    assert window.worker.options["model_path"] == "models/yolov8s-oiv7.pt"
    assert "577" in window.model_note.text()
    assert "experimental" in window.model_note.text()
    assert not window.worker.starts
