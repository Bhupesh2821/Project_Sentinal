"""Owner-local camera catalog, explicit selection and bounded connection tests."""
from datetime import datetime,timezone
import threading
from time import monotonic

from PySide6.QtCore import Qt,QThread,Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,
    QPushButton,QComboBox,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView)
from sentinal.core.credentials import CredentialError
from sentinal.storage.camera_registry import CameraRegistry
from sentinal.vision.camera_manager import discover_cameras
from sentinal.vision.live_capture import LiveVideoSource
from sentinal.vision.video_source import VideoSourceError
from sentinal.interface.network_camera_dialog import NetworkCameraDialog


class ConnectionTestWorker(QThread):
    completed=Signal(object)
    def __init__(self,selection,parent=None):
        super().__init__(parent);self.selection=selection;self._cancel=threading.Event()
    def cancel(self):self._cancel.set()
    def run(self):
        source=None;result={'passed':False,'cancelled':False}
        started=monotonic()
        try:
            if self._cancel.is_set():return
            source=LiveVideoSource(self.selection.spec,open_timeout_ms=5000,read_timeout_ms=2000)
            source.open()
            if self._cancel.is_set():result['cancelled']=True;return
            frame=source.read()
            result.update(passed=frame is not None,shape=list(frame.shape),frame_utc=datetime.now(timezone.utc).isoformat(timespec='milliseconds'))
            del frame
        except VideoSourceError:
            result['message']='Connection test failed. Check the selected camera, address, credentials and access permissions.'
        except Exception:
            result['message']='Connection test could not complete. Check the source configuration and retry.'
        finally:
            if source is not None:
                try:source.close()
                except Exception:result['passed']=False;result['message']='The connection did not release cleanly. Close SENTINAL before retrying.'
            result['cancelled']=result['cancelled'] or self._cancel.is_set()
            result['elapsed_s']=monotonic()-started
            result['resources_released']=source is None or source.capture is None
            self.completed.emit(result)


class CameraManagerDialog(QDialog):
    camera_selected=Signal(object)
    cameras_selected=Signal(object)
    setup_finished=Signal()
    def __init__(self,parent=None,registry=None,credentials=None):
        super().__init__(parent)
        self.registry=registry or CameraRegistry(credentials=credentials)
        self._owns_registry=registry is None
        self._test_worker=None;self._network_dialog=None;self._closing=False;self._monitoring_active=False
        self._selected_id=None;self._checked_ids=set()
        self.setWindowTitle('SENTINAL · Camera management')
        self.resize(1030,730)
        layout=QVBoxLayout(self)
        note=QLabel('Add cameras or find nearby CCTV, then check the saved cameras you want to monitor together. Use checked cameras returns your selection to the camera wall; Start remains an explicit action. Use camera selects one source.')
        note.setWordWrap(True);layout.addWidget(note)
        self.table=QTableWidget(0,8)
        self.table.setHorizontalHeaderLabels(['Choose / Name','Host','Type','Connection','Authentication','AI','Last frame (UTC)','Profile'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selected)
        self.table.itemChanged.connect(self._checked_changed)
        layout.addWidget(self.table,1)
        form=QHBoxLayout();self.kind=QComboBox();self.kind.addItems(['Network camera','Local Mac / iPhone / external camera'])
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.name=QLineEdit();self.name.setPlaceholderText('Camera name, e.g. Main Entrance')
        form.addWidget(self.kind);form.addWidget(self.name,1);layout.addLayout(form)
        local=QHBoxLayout();self.local_camera=QComboBox();local.addWidget(self.local_camera,1)
        self.refresh_button=QPushButton('Refresh local cameras');self.refresh_button.clicked.connect(self.refresh_local);local.addWidget(self.refresh_button);layout.addLayout(local)
        self.endpoint=QLineEdit();self.endpoint.setPlaceholderText('rtsp://camera-address/stream or compatible HTTP video endpoint');layout.addWidget(self.endpoint)
        credential_row=QHBoxLayout();self.username=QLineEdit();self.username.setPlaceholderText('Username');self.password=QLineEdit();self.password.setPlaceholderText('Password');self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.profile=QLineEdit();self.profile.setPlaceholderText('Selected profile name, if known')
        for widget in (self.username,self.password,self.profile):credential_row.addWidget(widget)
        layout.addLayout(credential_row)
        self.remember=QCheckBox('Remember full stream address and credentials in macOS Keychain')
        self.remember.setChecked(False);layout.addWidget(self.remember)
        privacy=QLabel('Off by default. Project configuration stores only name, host, protocol, profile and status. Full paths, query tokens and passwords stay in memory or in Keychain only after explicit saving. No plaintext fallback.')
        privacy.setWordWrap(True);privacy.setObjectName('muted');layout.addWidget(privacy)
        buttons=QHBoxLayout()
        self.new_button=QPushButton('New');self.save_button=QPushButton('Save camera');self.onvif_button=QPushButton('Nearby CCTV…');self.test_button=QPushButton('Test connection');self.remove_button=QPushButton('Remove selected')
        self.new_button.clicked.connect(self.new_camera);self.save_button.clicked.connect(self.save_camera);self.onvif_button.clicked.connect(self.open_onvif);self.test_button.clicked.connect(self.test_selected);self.remove_button.clicked.connect(self.remove_selected)
        for widget in (self.new_button,self.save_button,self.onvif_button,self.test_button,self.remove_button):buttons.addWidget(widget)
        layout.addLayout(buttons)
        self.status=QLabel('No capture has started. Select a saved camera or add a new one.');self.status.setWordWrap(True);layout.addWidget(self.status)
        actions=QHBoxLayout();self.close_button=QPushButton('Close');self.close_button.clicked.connect(self.close);self.use_button=QPushButton('Use camera');self.use_button.setObjectName('primary');self.use_button.clicked.connect(self.use_selected)
        self.use_checked_button=QPushButton('Use checked cameras (0)');self.use_checked_button.setObjectName('primary');self.use_checked_button.clicked.connect(self.use_checked)
        actions.addWidget(self.close_button);actions.addStretch();actions.addWidget(self.use_button);actions.addWidget(self.use_checked_button);layout.addLayout(actions)
        self.refresh_local();self.refresh();self._kind_changed()

    @property
    def setup_running(self):return self._test_worker is not None or (self._network_dialog is not None and self._network_dialog.setup_running)
    def set_monitoring_active(self,active):
        self._monitoring_active=bool(active);self._controls()
    def refresh(self):
        selected=self._selected_id
        valid_ids={record.camera_id for record in self.registry.list_cameras()}
        self._checked_ids.intersection_update(valid_ids)
        self.table.blockSignals(True);records=self.registry.list_cameras();self.table.setRowCount(len(records))
        for row,record in enumerate(records):
            values=[record.name,record.host,record.connection_type,record.connection_health,record.authentication_status,record.ai_status,record.last_frame_utc or '—',record.profile_name]
            for col,value in enumerate(values):
                item=QTableWidgetItem(str(value));item.setData(Qt.ItemDataRole.UserRole,record.camera_id)
                if col==0:
                    item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if record.camera_id in self._checked_ids else Qt.CheckState.Unchecked)
                self.table.setItem(row,col,item)
            if record.camera_id==selected:self.table.selectRow(row)
        self.table.blockSignals(False);self._controls()
    def refresh_local(self):
        previous=self.local_camera.currentData();self.local_camera.clear();self.local_camera.addItem('Choose an exact local camera…',None)
        for device in discover_cameras():
            self.local_camera.addItem(f'{device.category} · {device.name}',device)
            if previous is not None and previous.device_id==device.device_id:self.local_camera.setCurrentIndex(self.local_camera.count()-1)
    def _kind_changed(self,*_):
        local=self.kind.currentIndex()==1
        self.local_camera.setVisible(local);self.refresh_button.setVisible(local)
        for widget in (self.endpoint,self.username,self.password,self.profile,self.remember,self.onvif_button):widget.setVisible(not local)
    def _controls(self):
        busy=self.setup_running or self._closing
        for widget in (self.new_button,self.save_button,self.onvif_button,self.remove_button,self.table,self.kind,self.name,self.endpoint,self.username,self.password,self.profile,self.remember,self.local_camera,self.refresh_button):widget.setEnabled(not busy)
        self.test_button.setEnabled(bool(self._selected_id) and not busy and not self._monitoring_active)
        self.use_button.setEnabled(bool(self._selected_id) and not busy and not self._monitoring_active)
        self.use_checked_button.setText(f'Use checked cameras ({len(self._checked_ids)})')
        self.use_checked_button.setEnabled(bool(self._checked_ids) and not busy and not self._monitoring_active)
    def _checked_changed(self,item):
        if item.column()!=0:return
        ident=item.data(Qt.ItemDataRole.UserRole)
        if item.checkState()==Qt.CheckState.Checked:self._checked_ids.add(ident)
        else:self._checked_ids.discard(ident)
        self._controls()

    def use_checked(self):
        if not self._checked_ids or self.setup_running or self._monitoring_active:return
        try:
            selections=tuple(self.registry.resolve(record.camera_id) for record in self.registry.list_cameras() if record.camera_id in self._checked_ids)
            if not selections:raise ValueError('No saved cameras selected')
        except (ValueError,CredentialError):
            self.status.setText('A checked camera cannot be resolved. Re-enter its session-only address/credentials or uncheck it. No cameras were started.')
            return
        self.cameras_selected.emit(selections)
        self.close()

    def _selected(self):
        items=self.table.selectedItems()
        if not items:return
        self._selected_id=items[0].data(Qt.ItemDataRole.UserRole)
        record=self.registry.get(self._selected_id)
        if record is None:return
        self.name.setText(record.name);self.kind.setCurrentIndex(1 if record.source_kind=='camera' else 0);self.profile.setText(record.profile_name);self.remember.setChecked(record.remember)
        self.endpoint.clear();self.username.clear();self.password.clear()
        if record.source_kind=='camera':
            index=next((i for i in range(self.local_camera.count()) if getattr(self.local_camera.itemData(i),'device_id',None)==record.camera_device_id),0);self.local_camera.setCurrentIndex(index)
        else:
            try:
                selection=self.registry.resolve(record.camera_id);self.endpoint.setText(selection.endpoint);self.username.setText(selection.username);self.password.setText(selection.password)
            except CredentialError as exc:self.status.setText(str(exc))
        self._controls()
    def new_camera(self):
        self._selected_id=None;self.table.clearSelection();self.name.clear();self.endpoint.clear();self.username.clear();self.password.clear();self.profile.clear();self.remember.setChecked(False);self._controls()
    def save_camera(self):
        try:
            if self.kind.currentIndex()==1:
                device=self.local_camera.currentData()
                if device is None:raise ValueError('Choose the exact local camera first')
                record=self.registry.upsert_local(self.name.text(),device.device_id,device.index,camera_id=self._selected_id)
            else:record=self.registry.upsert_network(self.name.text(),self.endpoint.text().strip(),self.username.text(),self.password.text(),self.profile.text(),self.remember.isChecked(),camera_id=self._selected_id)
            self._selected_id=record.camera_id;self.status.setText('Camera saved. No capture was started. Test or explicitly use this camera.');self.refresh()
        except (ValueError,CredentialError,PermissionError):self.status.setText('Camera could not be saved. Check its name/address and Keychain permission. No plaintext fallback was created.')
        except Exception:self.status.setText('Camera configuration could not be saved. Check local storage and retry.')
    def open_onvif(self):
        if self._network_dialog is None:
            self._network_dialog=NetworkCameraDialog(self);self._network_dialog.stream_selected.connect(self._on_onvif);self._network_dialog.setup_finished.connect(self._setup_finished)
        self._network_dialog.show();self._network_dialog.raise_()
    def _on_onvif(self,url,username,password):
        self.kind.setCurrentIndex(0);self.endpoint.setText(url);self.username.setText(username);self.password.setText(password)
        self.status.setText('ONVIF stream returned. Assign a name and Save camera. No video connection has started.')
    def use_selected(self):
        if self._selected_id is None or self._monitoring_active:return
        try:selection=self.registry.resolve(self._selected_id)
        except (ValueError,CredentialError) as exc:self.status.setText(str(exc));return
        self.camera_selected.emit(selection);self.close()
    def remove_selected(self):
        if not self._selected_id:return
        try:self.registry.remove(self._selected_id);self.new_camera();self.refresh();self.status.setText('Camera configuration and saved credential removed.')
        except CredentialError as exc:self.status.setText(str(exc))
    def test_selected(self):
        if not self._selected_id or self.setup_running or self._monitoring_active:return
        try:selection=self.registry.resolve(self._selected_id)
        except (ValueError,CredentialError) as exc:self.status.setText(str(exc));return
        self.registry.update_health(self._selected_id,connection_health='connecting',ai_status='idle')
        self._test_worker=ConnectionTestWorker(selection,self);self._test_worker.completed.connect(self._test_result);self._test_worker.finished.connect(self._test_finished)
        self.status.setText('Testing selected connection by reading one actual frame; no image is saved…');self._controls();self._test_worker.start()
    def _test_result(self,result):
        if result.get('cancelled'):
            self.registry.update_health(self._selected_id,connection_health='stopped' if result.get('resources_released') else 'error',ai_status='idle')
            self.status.setText('Connection test cancelled. Monitoring is stopped.');self.refresh();return
        if result.get('passed'):
            selection=self.registry.resolve(self._selected_id)
            authenticated='authenticated' if selection.username or selection.password else 'not_required'
            self.registry.update_health(self._selected_id,connection_health='stopped',frame_timestamp=result['frame_utc'],ai_status='idle',authentication_status=authenticated)
            self.status.setText(f'Connection test received {result["shape"][1]} × {result["shape"][0]} in {result["elapsed_s"]:.2f}s, then released it. Monitoring remains stopped.')
        else:
            self.registry.update_health(self._selected_id,connection_health='error',ai_status='idle');self.status.setText(result.get('message','Connection test failed.'))
        self.refresh()
    def _test_finished(self):
        worker,self._test_worker=self._test_worker,None
        if worker is not None:worker.deleteLater()
        self._setup_finished()
    def _setup_finished(self):
        self._controls();self.setup_finished.emit()
        if self._closing and not self.setup_running:self.close()
    def cancel_setup(self):
        if self._test_worker is not None:self._test_worker.cancel()
        if self._network_dialog is not None:self._network_dialog.cancel_setup()
    def wait_for_setup(self):
        self.cancel_setup()
        if self._test_worker is not None:self._test_worker.wait()
        if self._network_dialog is not None:self._network_dialog.wait_for_setup()
    def closeEvent(self,event):
        if self.setup_running:
            event.ignore();self._closing=True;self.cancel_setup();self._controls();return
        self._closing=False;self._controls()
        self.password.clear()
        if self._network_dialog is not None:self._network_dialog.close()
        event.accept()
