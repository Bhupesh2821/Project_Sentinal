"""Explicit network-camera setup; discovering profiles never opens a video feed."""
import threading
from datetime import datetime, timezone
from urllib.parse import urlsplit

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QLineEdit, QComboBox, QListWidget, QListWidgetItem)

from sentinal.vision.network_discovery import discover_cameras, discovery_interfaces, NetworkCameraError
from sentinal.vision.onvif_client import OnvifClient


class CameraSetupWorker(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, mode, address="", username="", password="", parent=None, interface_address=None):
        super().__init__(parent)
        self.mode = mode
        self.interface_address = interface_address
        self._address, self._username, self._password = address, username, password
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            if self.mode == "discover":
                result = discover_cameras(timeout_s=3.0, cancel_event=self._cancel, interface_address=self.interface_address)
            else:
                result = OnvifClient(self._address, self._username, self._password,
                                     timeout_s=3.0, cancel_event=self._cancel).list_streams()
            if not self._cancel.is_set():
                self.result.emit(result)
        except NetworkCameraError as exc:
            if not self._cancel.is_set():
                self.failed.emit(str(exc))
        except Exception:
            if not self._cancel.is_set():
                self.failed.emit("Camera setup could not complete. Check its ONVIF address and local-network access, or enter the video address directly in the main window.")
        finally:
            self._address = self._username = self._password = ""


class NetworkCameraDialog(QDialog):
    stream_selected = Signal(str, str, str)
    # The owning window can defer destruction/quit until this signal arrives.
    setup_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._pending_result = None
        self._stream_credentials = ("", "")
        self._streams = []
        self._address_host = None
        self.setWindowTitle("SENTINAL · Nearby CCTV / network camera")
        self.setMinimumWidth(780)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        intro = QLabel("Nearby CCTV lists cameras that reply on your selected local network. Connect this Mac and the cameras/NVR to the same reachable Wi-Fi or Ethernet network. Select a camera and authenticate; video starts only after an explicit Start.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        network_row = QHBoxLayout()
        network_row.addWidget(QLabel('Network'))
        self.network_combo = QComboBox()
        network_row.addWidget(self.network_combo, 1)
        self.refresh_networks_button = QPushButton('Refresh networks')
        self.refresh_networks_button.clicked.connect(self.refresh_networks)
        network_row.addWidget(self.refresh_networks_button)
        layout.addLayout(network_row)
        self.refresh_networks()
        self.discover_button = QPushButton('Refresh nearby CCTV list')
        self.discover_button.clicked.connect(self.discover)
        layout.addWidget(self.discover_button)
        self.camera_list = QListWidget()
        self.camera_list.setMinimumHeight(165)
        self.camera_list.setMaximumHeight(260)
        self.camera_list.itemSelectionChanged.connect(self._camera_selected)
        layout.addWidget(self.camera_list)
        self.address = QLineEdit()
        self.address.setPlaceholderText("http://192.168.1.100/onvif/device_service")
        self.address.setClearButtonEnabled(True)
        self.address.textChanged.connect(self._address_changed)
        layout.addWidget(self.address)
        credentials = QHBoxLayout()
        self.username = QLineEdit()
        self.username.setPlaceholderText("ONVIF username")
        self.password = QLineEdit()
        self.password.setPlaceholderText("ONVIF password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.username.textChanged.connect(self._clear_streams)
        self.password.textChanged.connect(self._clear_streams)
        credentials.addWidget(self.username)
        credentials.addWidget(self.password)
        layout.addLayout(credentials)
        self.profiles_button = QPushButton("Get video streams")
        self.profiles_button.clicked.connect(self.load_profiles)
        layout.addWidget(self.profiles_button)
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._profile_selected)
        layout.addWidget(self.profile_combo)
        self.stream_hint = QLabel("No stream selected")
        self.stream_hint.setWordWrap(True)
        layout.addWidget(self.stream_hint)
        self.status = QLabel("Press Refresh nearby CCTV list to look for advertised camera services. Discovery does not open video feeds or sign in automatically.")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(54)
        layout.addWidget(self.status)
        limits = QLabel("This is a discoverable-CCTV list, not a list of Wi-Fi access points. Only compatible ONVIF devices that reply on the chosen IPv4 network appear. Separate VLANs, guest/client isolation, disabled ONVIF and cloud-only cameras can prevent discovery. Enable ONVIF or enter an authorized address manually. If macOS blocks access, check System Settings → Privacy & Security → Local Network for the application that launched SENTINAL. Credentials stay in memory.")
        limits.setWordWrap(True)
        limits.setObjectName("muted")
        layout.addWidget(limits)
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton("Close")
        self.cancel_button.clicked.connect(self.reject)
        self.use_button = QPushButton("Use selected stream")
        self.use_button.setObjectName("primary")
        self.use_button.setEnabled(False)
        self.use_button.clicked.connect(self.use_selected)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        buttons.addWidget(self.use_button)
        layout.addLayout(buttons)
        self._clear_streams()

    def refresh_networks(self):
        previous = self.network_combo.currentData()
        self.network_combo.clear()
        self.network_combo.addItem('Automatic route · current connected network', None)
        for interface in discovery_interfaces():
            self.network_combo.addItem(interface.description, interface.address)
        index = self.network_combo.findData(previous)
        if index >= 0:self.network_combo.setCurrentIndex(index)

    @property
    def setup_running(self):
        return self._worker is not None

    def cancel_setup(self):
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("Cancelling camera setup…")

    def wait_for_setup(self):
        """Final application shutdown safety, after requesting cancellation."""
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait()

    def _clear_streams(self, *_):
        self._streams = []
        self._stream_credentials = ("", "")
        if hasattr(self, "profile_combo"):
            self.profile_combo.clear()
            self.profile_combo.addItem("Choose a returned video stream…", None)
        if hasattr(self, "use_button"):
            self.use_button.setEnabled(False)
        if hasattr(self, "stream_hint"):
            self.stream_hint.setText("No stream selected")

    def _address_changed(self, text):
        try:
            host = (urlsplit(text.strip()).hostname or "").casefold()
        except ValueError:
            host = ""
        if self._address_host is not None and host != self._address_host:
            self.username.clear()
            self.password.clear()
        self._address_host = host
        self._clear_streams()

    def _camera_selected(self):
        items = self.camera_list.selectedItems()
        if items:
            self.address.setText(items[0].data(Qt.ItemDataRole.UserRole))

    def _set_busy(self, busy):
        for widget in (self.discover_button, self.profiles_button, self.address,
                       self.username, self.password, self.camera_list, self.profile_combo, self.network_combo, self.refresh_networks_button):
            widget.setEnabled(not busy)
        self.use_button.setEnabled(not busy and self.profile_combo.currentData() is not None)
        self.cancel_button.setText("Cancel setup" if busy else "Close")

    def _begin(self, mode):
        if self._worker is not None:
            return
        self._clear_streams()
        self._set_busy(True)
        if mode == 'discover':
            self.camera_list.clear()
            self.status.setText('Refreshing nearby CCTV on ' + self.network_combo.currentText() + '…')
        else:self.status.setText('Requesting camera video profiles…')
        worker = CameraSetupWorker(mode, self.address.text().strip(), self.username.text(), self.password.text(), self, interface_address=self.network_combo.currentData())
        self._worker = worker
        worker.result.connect(self._discovered if mode == "discover" else self._profiles_loaded)
        worker.failed.connect(self.status.setText)
        worker.finished.connect(self._finished)
        worker.start()

    def discover(self):
        self._begin("discover")

    def load_profiles(self):
        if not self.address.text().strip():
            self.status.setText("Enter or select the ONVIF camera address first.")
            return
        self._begin("profiles")

    def _discovered(self, devices):
        if self._pending_result is not None:
            return
        self.camera_list.clear()
        for device in devices:
            item = QListWidgetItem(device.description + "  ·  ONVIF advertised")
            item.setData(Qt.ItemDataRole.UserRole, device.device_url)
            self.camera_list.addItem(item)
        refreshed = datetime.now(timezone.utc).isoformat(timespec='seconds')
        self.status.setText(f'{len(devices)} nearby camera service(s) replied · refreshed {refreshed}. Select one and get its video streams. Sign-in/video health is not yet verified.' if devices else 'No compatible camera replied to this refresh. Try the correct network interface, enable ONVIF, check client isolation and macOS Local Network permission, or enter the authorized camera address manually. This does not prove that no cameras are connected.')

    def _profiles_loaded(self, streams):
        if self._pending_result is not None:
            return
        self._streams = list(streams)
        self._stream_credentials = (self.username.text(), self.password.text())
        self.profile_combo.clear()
        for index, stream in enumerate(self._streams):
            self.profile_combo.addItem(stream.description, index)
        self._profile_selected()
        self.status.setText(f"Returned {len(streams)} stream(s). Choose one and use it, then press Start monitoring in the main window.")

    def _profile_selected(self, *_):
        index = self.profile_combo.currentData()
        valid = type(index) is int and 0 <= index < len(self._streams)
        self.use_button.setEnabled(valid and self._worker is None)
        if valid:
            parts = urlsplit(self._streams[index].uri)
            self.stream_hint.setText(f"{parts.scheme.upper()} video from {parts.hostname} · full endpoint stays in memory")

    def _finished(self):
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._set_busy(False)
        self.setup_finished.emit()
        if self._pending_result is not None:
            result, self._pending_result = self._pending_result, None
            self.password.clear()
            super().done(result)

    def use_selected(self):
        if self._worker is not None:
            return
        index = self.profile_combo.currentData()
        if type(index) is not int or not 0 <= index < len(self._streams):
            return
        uri = self._streams[index].uri
        username, password = self._stream_credentials
        self.stream_selected.emit(uri, username, password)
        self.done(QDialog.DialogCode.Accepted)

    def done(self, result):
        if self._worker is not None:
            self._pending_result = result
            self.cancel_setup()
            return
        self.password.clear()
        self._clear_streams()
        super().done(result)

    def closeEvent(self, event):
        if self._worker is not None:
            event.ignore()
            self._pending_result = QDialog.DialogCode.Rejected
            self.cancel_setup()
        else:
            self.password.clear()
            event.accept()
