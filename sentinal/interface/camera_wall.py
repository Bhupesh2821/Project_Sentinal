"""Explicit, bounded simultaneous monitoring using the existing camera adapters."""
import time
from PySide6.QtCore import Qt,QTimer,Signal,QSignalBlocker
from PySide6.QtWidgets import (QDialog,QWidget,QFrame,QLabel,QPushButton,
    QVBoxLayout,QHBoxLayout,QGridLayout,QScrollArea,QTableWidget,QTableWidgetItem,
    QCheckBox,QComboBox,QSplitter)
from sentinal.vision.multi_camera import MultiCameraWorker
from sentinal.interface.video_panel import VideoPanel

class CameraTile(QFrame):
    stop_requested=Signal(str)
    def __init__(self,selection,parent=None):
        super().__init__(parent);self.ident=selection.record.camera_id
        self.setObjectName('sidebar');layout=QVBoxLayout(self)
        header=QHBoxLayout();self.name=QLabel(selection.record.name);header.addWidget(self.name,1)
        self.stop_button=QPushButton('Stop');self.stop_button.clicked.connect(lambda:self.stop_requested.emit(self.ident));header.addWidget(self.stop_button)
        layout.addLayout(header);self.video=VideoPanel();self.video.setMinimumSize(320,200);layout.addWidget(self.video,1)
        self.status=QLabel('Selected · not monitoring');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.observations=QLabel('Hazard analysis has not sampled this source.');self.observations.setWordWrap(True);layout.addWidget(self.observations)
        self.metrics=QLabel('No fresh inference');self.metrics.setWordWrap(True);layout.addWidget(self.metrics)
        self.alert=QLabel();self.alert.setWordWrap(True);self.alert.setStyleSheet('color: #ffca70;');self.alert.hide();layout.addWidget(self.alert)
        self.incident_id=None;self.last_packet=None
    def set_state(self,state,message):
        self.status.setText(state.upper()+' · '+message)
        self.stop_button.setEnabled(state in {'loading','running','reconnecting'})
        if state in {'loading','reconnecting','stopping','stopped','eof','error'}:
            self.video.clear_frame(state.upper());self.metrics.setText('No active inference');self.observations.setText('No current hazard analysis · '+state);self.last_packet=None
    def set_packet(self,packet,hazards_enabled=False):
        self.last_packet=packet;self.video.present_packet(packet,hazards_enabled=hazards_enabled)
        if packet.hazard_sampled:
            unavailable=[name for name,health in packet.detector_health.items() if health.get('status')=='unavailable']
            labels=[h.category.replace('weapon_','').replace('_',' ')+f' {h.confidence:.0%}' for h in packet.hazards]
            text=('POSSIBLE: '+', '.join(labels)) if labels else 'No possible hazards in this analyzed sample'
            if unavailable:text+=' · Unavailable: '+', '.join(unavailable)
            self.observations.setText(text+' · '+packet.timestamp)
        self.metrics.setText(f'{packet.fps:.1f} analyzed FPS · {packet.inference_ms:.0f} ms inference · age {packet.frame_age_ms:.0f} ms · skipped {packet.dropped_frames}\n'+packet.timestamp)

class CameraWallDialog(QDialog):
    activity_changed=Signal()
    setup_finished=Signal()
    def __init__(self,main,registry):
        super().__init__(main);self.main=main;self.registry=registry
        self._closing=False;self._closed=False;self._selected={};self.tiles={};self.states={}
        self._health_times={};self._last_activity=False;self._incident_connected=False
        self.setWindowTitle('SENTINAL · Multi-camera monitoring');self.resize(1430,930)
        layout=QVBoxLayout(self);self.summary=QLabel('No cameras monitoring. Select saved cameras, then Start checked.');layout.addWidget(self.summary)
        alerts=QHBoxLayout();self.alert_summary=QLabel('No new alerts in this monitoring window.');self.alert_summary.setWordWrap(True);alerts.addWidget(self.alert_summary,1)
        review=QPushButton('Review incidents…');review.clicked.connect(self._open_incidents);alerts.addWidget(review);layout.addLayout(alerts)
        split=QSplitter();layout.addWidget(split,1)
        controls=QWidget();side=QVBoxLayout(controls)
        info=QLabel('Up to 8 selected sources. Cameras capture independently; shared models analyze them fairly. More cameras reduce per-camera processing rate.');info.setWordWrap(True);side.addWidget(info)
        setup=QPushButton('Nearby CCTV / camera setup…');setup.clicked.connect(main.open_camera_manager);side.addWidget(setup)
        refresh=QPushButton('Refresh saved cameras');refresh.clicked.connect(self.refresh);side.addWidget(refresh)
        self.table=QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['Use','Saved camera']);self.table.setColumnWidth(0,40);self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);side.addWidget(self.table,1)
        self.hazards=QCheckBox('Analyze possible weapons / fire');self.hazards.setChecked(main.hazards_toggle.isChecked());self.hazards.toggled.connect(main.hazards_toggle.setChecked);main.hazards_toggle.toggled.connect(self.hazards.setChecked);side.addWidget(self.hazards)
        self.record=QCheckBox('Save incident metadata');self.record.setChecked(main.incident_record_toggle.isChecked());self.record.toggled.connect(main.incident_record_toggle.setChecked);main.incident_record_toggle.toggled.connect(self.record.setChecked);side.addWidget(self.record)
        self.evidence=QCheckBox('Save evidence snapshots');self.evidence.setChecked(main.evidence_toggle.isChecked());self.evidence.setEnabled(self.record.isChecked());self.evidence.toggled.connect(main.evidence_toggle.setChecked);main.evidence_toggle.toggled.connect(self.evidence.setChecked);self.record.toggled.connect(self.evidence.setEnabled);side.addWidget(self.evidence)
        self.model_combo=QComboBox()
        for i in range(main.model_combo.count()):self.model_combo.addItem(main.model_combo.itemText(i),main.model_combo.itemData(i))
        self.model_combo.setCurrentIndex(main.model_combo.currentIndex());self.model_combo.currentIndexChanged.connect(self._choose_object_model);main.model_combo.currentIndexChanged.connect(self.model_combo.setCurrentIndex)
        self.model_combo.setEnabled(not main._busy and not main._closing and not main._worker_dead)
        side.addWidget(QLabel('Object model (change while stopped)'));side.addWidget(self.model_combo)
        self.filter_combo=QComboBox()
        for i in range(main.filter_combo.count()):self.filter_combo.addItem(main.filter_combo.itemText(i))
        self.filter_combo.setCurrentIndex(main.filter_combo.currentIndex());self.filter_combo.currentIndexChanged.connect(main.filter_combo.setCurrentIndex);main.filter_combo.currentIndexChanged.connect(self.filter_combo.setCurrentIndex)
        side.addWidget(QLabel('Display object categories'));side.addWidget(self.filter_combo)
        enable=QPushButton('Show all objects + enable hazard models');enable.clicked.connect(main.enable_all_detection);side.addWidget(enable)
        settings=QPushButton('Detection / alert settings…');settings.clicked.connect(main.open_control_center);side.addWidget(settings)
        self.start_button=QPushButton('Start checked cameras');self.start_button.setObjectName('primary');self.start_button.clicked.connect(self.start_checked);side.addWidget(self.start_button)
        self.stop_all=QPushButton('Stop all cameras');self.stop_all.clicked.connect(lambda:self.worker.request_stop());self.stop_all.setEnabled(False);side.addWidget(self.stop_all)
        self.message=QLabel('Recording, snapshots and audio follow the explicit controls. No discovery action starts video.');self.message.setWordWrap(True);side.addWidget(self.message)
        close=QPushButton('Close and release cameras');close.clicked.connect(self.close);side.addWidget(close)
        split.addWidget(controls)
        area=QScrollArea();area.setWidgetResizable(True);shell=QWidget();self.grid=QGridLayout(shell);area.setWidget(shell);split.addWidget(area);split.setSizes([310,1100])
        self.worker=MultiCameraWorker(main.config,self,max_cameras=8)
        self.worker.state_changed.connect(self._on_state);self.worker.error.connect(self._on_error);self.worker.finished.connect(self._finished)
        self.worker.start();self.timer=QTimer(self);self.timer.setInterval(40);self.timer.timeout.connect(self._poll);self.timer.start()
        self.refresh();self.apply_options()
    @property
    def setup_running(self):return self.worker.isRunning()
    @property
    def is_monitoring(self):return self.worker.is_monitoring or any(state in {'loading','running','reconnecting','stopping'} for state in self.states.values())
    def refresh(self):
        checked={self.table.item(i,0).data(Qt.ItemDataRole.UserRole) for i in range(self.table.rowCount()) if self.table.item(i,0).checkState()==Qt.CheckState.Checked}
        if not self.table.rowCount():checked.update(self._selected)
        records=self.registry.list_cameras();self.table.setRowCount(len(records))
        for i,record in enumerate(records):
            item=QTableWidgetItem();item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsUserCheckable);item.setData(Qt.ItemDataRole.UserRole,record.camera_id);item.setCheckState(Qt.CheckState.Checked if record.camera_id in checked else Qt.CheckState.Unchecked)
            self.table.setItem(i,0,item);self.table.setItem(i,1,QTableWidgetItem(record.name+' · '+record.connection_type))
    def set_selections(self,selections):
        if self._closing:return
        self._selected={selection.record.camera_id:selection for selection in selections};self.refresh()
        for i in range(self.table.rowCount()):
            item=self.table.item(i,0);item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in self._selected else Qt.CheckState.Unchecked)
        self.message.setText(f'{len(selections)} cameras selected. Press Start checked cameras to begin.')
    def start_checked(self):
        if self._closing:return
        if self.main._busy:self.message.setText('Stop single-source monitoring before starting the camera wall.');return
        try:
            identities=[self.table.item(i,0).data(Qt.ItemDataRole.UserRole) for i in range(self.table.rowCount()) if self.table.item(i,0).checkState()==Qt.CheckState.Checked]
            if not 1<=len(identities)<=8:raise ValueError('Select between 1 and 8 saved cameras.')
            selections=[self.registry.resolve(ident) for ident in identities]
            self.start_selections(selections)
        except Exception:self.message.setText('Could not start the selection. Choose 1–8 cameras and check their saved address / credentials.')
    def start_selections(self,selections):
        if self.main._busy:raise ValueError('Stop the single source first')
        self.apply_options()
        selections=tuple(selections)
        if not self.worker.request_start(selections):raise ValueError('The camera worker is shutting down. Close and reopen the monitoring window.')
        self._selected={s.record.camera_id:s for s in selections}
        for ident,tile in list(self.tiles.items()):
            if ident not in self._selected:self.grid.removeWidget(tile);tile.deleteLater();self.tiles.pop(ident);self.states.pop(ident,None)
        for index,selection in enumerate(selections):
            ident=selection.record.camera_id
            if ident not in self.tiles:
                tile=CameraTile(selection,self);tile.stop_requested.connect(self.worker.request_stop);self.tiles[ident]=tile
            self.grid.addWidget(self.tiles[ident],index//2,index%2)
            if self.states.get(ident) not in {'loading','running','reconnecting'}:
                self.states[ident]='loading';self.tiles[ident].set_state('loading','Waiting for selected source')
        self.message.setText('Opening only the explicitly selected sources…');self.stop_all.setEnabled(True);self.model_combo.setEnabled(False);self.activity_changed.emit()
    def _choose_object_model(self,index):
        if self.main._busy or self.main._closing or self.main._worker_dead or self._closing or self.is_monitoring:
            with QSignalBlocker(self.model_combo):self.model_combo.setCurrentIndex(self.main.model_combo.currentIndex())
            return
        self.main.model_combo.setCurrentIndex(index)
    def apply_options(self):
        if self._closing:return
        self.worker.set_options(confidence=self.main.confidence_slider.value()/100,image_size=int(self.main.resolution_combo.currentData()),model_path=self.main.model_combo.currentData(),category_filter=('all','focus','safety')[self.main.filter_combo.currentIndex()],hazards_enabled=self.main.hazards_toggle.isChecked(),hazard_settings=self.main.hazard_settings)
        if self.main.hazards_toggle.isChecked():
            service=self.main._ensure_incidents()
            if not self._incident_connected:
                service.incident_changed.connect(self._on_incident);self._incident_connected=True
            signature=(self.main.hazard_settings,self.main.incident_record_toggle.isChecked(),self.main.evidence_toggle.isChecked())
            if signature!=self.main._incident_options_signature:
                service.configure(self.main.hazard_settings,persist=signature[1],snapshots=signature[2]);self.main._incident_options_signature=signature
            self.worker.set_incident_consumer(service.submit_packet)
        else:self.worker.set_incident_consumer(None)
    def _open_incidents(self):
        self.main.open_control_center()
        self.main._control_center.tabs.setCurrentIndex(1)
        self.main._control_center.refresh()
    def _on_incident(self,row):
        ident=row.get('source_id');tile=self.tiles.get(ident)
        if tile is None:return
        status=row.get('status')
        if status=='ALERTED':
            tile.incident_id=row['incident_id']
            category=row['category'].replace('weapon_','').replace('_',' ').upper()
            text=f"POSSIBLE {category} · {row['confidence']:.0%} · Awaiting human verification\n{row['last_seen']}"
            tile.alert.setText(text);tile.alert.show()
            self.alert_summary.setText(tile.name.text()+' · '+text)
        elif status in {'ACKNOWLEDGED','VERIFIED','DISMISSED','CLOSED'} and tile.incident_id==row['incident_id']:
            text=f"Incident {row['incident_id'][:8]} · {status} · Human review recorded"
            tile.alert.setText(text);self.alert_summary.setText(tile.name.text()+' · '+text)
    def _on_state(self,ident,state,message):
        self.states[ident]=state
        if ident in self.tiles:self.tiles[ident].set_state(state,message)
        connection={'loading':'connecting','running':'online','reconnecting':'reconnecting','stopping':'stopped','stopped':'stopped','eof':'stopped','error':'error'}.get(state,'idle')
        try:self.registry.update_health(ident,connection_health=connection,ai_status='active' if state=='running' else 'error' if state=='error' else 'idle')
        except Exception:pass
        active=sum(value in {'loading','running','reconnecting','stopping'} for value in self.states.values())
        running=sum(value=='running' for value in self.states.values())
        self.summary.setText(f'{running} cameras analyzing · {active} active / connecting · {len(self.tiles)} selected')
        self.stop_all.setEnabled(bool(active));self.model_combo.setEnabled(not self.is_monitoring and not self.main._busy and not self.main._closing and not self.main._worker_dead and not self._closing);self.activity_changed.emit()
    def _on_error(self,ident,message):
        name=self._selected[ident].record.name if ident in self._selected else 'Camera'
        self.message.setText(name+' · '+message)
    def _poll(self):
        for ident,packet in self.worker.take_latest().items():
            if ident not in self.tiles or self.states.get(ident) not in {'loading','running'}:continue
            if self.states.get(ident)=='loading':self._on_state(ident,'running','Monitoring · fresh inference received')
            tile=self.tiles[ident]
            tile.video.set_annotations(self.main.boxes_toggle.isChecked(),self.main.labels_toggle.isChecked(),self.main.ids_toggle.isChecked())
            tile.set_packet(packet,hazards_enabled=self.main.hazards_toggle.isChecked())
            now=time.monotonic()
            if now-self._health_times.get(ident,0)>=1:
                self._health_times[ident]=now
                try:self.registry.update_health(ident,connection_health='online',ai_status='active',frame_timestamp=packet.timestamp)
                except Exception:self.message.setText('Camera health could not be saved. Check local storage permissions.')
        active=self.is_monitoring
        self.model_combo.setEnabled(not active and not self.main._busy and not self.main._closing and not self.main._worker_dead and not self._closing)
        if active!=self._last_activity:
            self._last_activity=active;self.activity_changed.emit()
        if active:self.main._refresh_control_center()
    def _finished(self):
        self.timer.stop()
        if not self._closing:
            for ident,tile in self.tiles.items():
                if self.states.get(ident) not in {'stopped','eof','error'}:self.states[ident]='error';tile.set_state('error','Monitoring worker stopped')
        self.close()
    def closeEvent(self,event):
        if self.worker.isRunning():
            event.ignore();self._closing=True;self.start_button.setEnabled(False)
            self.message.setText('Releasing all selected cameras and model resources…')
            self.worker.request_shutdown()
        else:
            self.timer.stop();self._selected.clear();
            for tile in self.tiles.values():tile.set_state('stopped','Resources released')
            self.states={ident:'stopped' for ident in self.states};self._closed=True;self.setup_finished.emit();self.activity_changed.emit();event.accept()
