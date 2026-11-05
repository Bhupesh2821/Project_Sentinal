"""Dynamic local video and live-feed dashboard; every source starts by user action."""
from pathlib import Path
import hashlib
import time
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QLabel, QPushButton, QComboBox, QCheckBox,
    QSlider, QFileDialog, QHBoxLayout, QVBoxLayout, QScrollArea, QLineEdit,
    QProgressBar,
)

from sentinal import __version__
from sentinal.config import ROOT
from sentinal.vision.video_source import SourceSpec
from sentinal.vision.camera_manager import discover_cameras
from sentinal.vision.object_catalog import MODEL_PROFILES, catalog_rows
from sentinal.interface.catalog_dialog import CatalogDialog
from sentinal.interface.network_camera_dialog import NetworkCameraDialog
from sentinal.vision.inference_worker import InferenceWorker
from sentinal.storage.video_library import VideoLibrary
from sentinal.interface.video_import_worker import VideoImportWorker
from sentinal.interface.video_panel import VideoPanel
from sentinal.interface.statistics_panel import StatisticsPanel
from sentinal.interface.camera_permission import CameraPermissionGate


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def clock_text(seconds):
    seconds = max(0, int(seconds or 0))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


class MainWindow(QMainWindow):
    def __init__(self, config, video_path=None):
        super().__init__()
        self.config = config
        self.video_path = None
        self._busy = False
        self._camera_permission = CameraPermissionGate(self)
        self._camera_permission.error.connect(self._show_error)
        self._camera_permission.pending_changed.connect(self._camera_permission_changed)
        self._closing = False
        self._worker_dead = False
        self._network_dialog = None
        self._camera_initialized = False
        self._selected_camera_id = None
        self._credential_endpoint = None
        self._state = "idle"
        self._current_spec = None
        self._pending_video_path = None
        self._import_worker = None
        self._playback = {"duration_s": 0.0, "position_s": 0.0, "can_seek": False}
        self.last_packet = None
        self._incident_worker = None
        self._control_center = None
        self._camera_registry = None
        self._camera_manager_dialog = None
        self._camera_wall = None
        self._alert_output = None
        self._edge_bridge = None
        self._connected_dialog = None
        self._connected_session = None
        self._registry_selection = None
        self._registry_camera_id = None
        self._active_source_id = ''
        self._last_runtime_refresh = 0.0
        self._last_camera_health = 0.0
        self._last_incident = None
        self._banner_incident_id = None
        self._incident_options_signature = None
        from sentinal.core.v02_settings import V02Settings
        try:
            self.hazard_settings = V02Settings.load()
            settings_error = None
        except (ValueError, TypeError, OSError):
            self.hazard_settings = V02Settings()
            settings_error = 'V0.2 preferences could not load; safe defaults are in use. Review AI settings.'
        self.video_library = VideoLibrary()
        self.setWindowTitle("SENTINAL · MARK-007 · Vision & Incident Core")
        self.resize(1430, 900)
        self.setMinimumSize(1100, 740)
        self.setAcceptDrops(True)
        self._build_interface()
        self.worker = InferenceWorker(config, self)
        self.worker.state_changed.connect(self._on_state)
        self.worker.error.connect(self._show_error)
        self.worker.metadata_failed.connect(self._metadata_error)
        self.worker.finished.connect(self._worker_finished)
        if hasattr(self.worker, "playback_changed"):
            self.worker.playback_changed.connect(self._on_playback)
        self.worker.start()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._poll_frame)
        self._timer.start()
        self.refresh_cameras()
        from PySide6.QtMultimedia import QMediaDevices
        self._media_devices = QMediaDevices(self)
        self._media_devices.videoInputsChanged.connect(self.refresh_cameras)
        self.refresh_library()
        if settings_error:self._show_error(settings_error)
        if video_path:
            self.load_video(video_path)

    def _build_interface(self):
        root = QWidget()
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(25, 17, 25, 18)
        page.setSpacing(17)
        header = QFrame()
        header.setObjectName("header")
        head = QHBoxLayout(header)
        head.setContentsMargins(0, 0, 0, 18)
        identity = QVBoxLayout()
        identity.setSpacing(4)
        identity.addWidget(label("SENTINAL", "brand"))
        identity.addWidget(label(f"MARK-007   /   VISION CORE   /   V{__version__}", "edition"))
        head.addLayout(identity)
        head.addStretch()
        self.control_center_button = QPushButton('Operator center…')
        self.control_center_button.clicked.connect(self.open_control_center)
        head.addWidget(self.control_center_button)
        self.connected_button=QPushButton('Connected command center…')
        self.connected_button.clicked.connect(self.open_connected_settings)
        head.addWidget(self.connected_button)
        self.camera_wall_button=QPushButton('Multi-camera monitor…')
        self.camera_wall_button.clicked.connect(self.open_camera_wall);head.addWidget(self.camera_wall_button)
        head.addWidget(label("LOCAL VISION  ·  HUMAN OVERSIGHT", "edition"))
        head.addSpacing(22)
        self.status_chip = label("●  STANDBY", "statusChip")
        head.addWidget(self.status_chip)
        page.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(18)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(290)
        side_shell = QVBoxLayout(sidebar)
        side_shell.setContentsMargins(1, 1, 1, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_content = QWidget()
        sidebar_content.setObjectName("sidebarContents")
        scroll.setWidget(sidebar_content)
        side_shell.addWidget(scroll)
        side = QVBoxLayout(sidebar_content)
        side.setContentsMargins(18, 19, 18, 18)
        side.setSpacing(11)
        side.addWidget(label("MONITORING SOURCE", "sectionTitle"))
        self.source_type = QComboBox()
        self.source_type.addItems(["Camera", "Local video file", "Network camera"])
        self.source_type.currentIndexChanged.connect(self._invalidate_camera_permission)
        self.source_type.currentIndexChanged.connect(self._source_type_changed)
        side.addWidget(self.source_type)
        camera_row = QHBoxLayout()
        camera_row.setSpacing(7)
        self.camera_combo = QComboBox()
        self.camera_combo.setMinimumWidth(0)
        self.camera_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.camera_combo.setMinimumContentsLength(12)
        self.camera_combo.currentIndexChanged.connect(self._camera_selection_changed)
        camera_row.addWidget(self.camera_combo, 1)
        self.refresh_button = QPushButton("↻")
        self.refresh_button.setFixedWidth(36)
        self.refresh_button.setToolTip("Refresh exact camera choices; request camera permission if needed, without starting capture")
        self.refresh_button.clicked.connect(self.request_camera_refresh)
        camera_row.addWidget(self.refresh_button)
        side.addLayout(camera_row)
        self.camera_note = label("Choose Mac, iPhone or another camera explicitly. No automatic substitution.", "muted")
        self.camera_note.setWordWrap(True)
        side.addWidget(self.camera_note)
        self.camera_manager_button = QPushButton('Manage named cameras…')
        self.camera_manager_button.clicked.connect(self.open_camera_manager)
        side.addWidget(self.camera_manager_button)

        self.stream_url = QLineEdit()
        self.stream_url.setPlaceholderText("rtsp://camera-address/stream")
        self.stream_url.setClearButtonEnabled(True)
        self.stream_url.editingFinished.connect(self._normalize_stream_fields)
        self.stream_url.setToolTip("RTSP, RTSPS, HTTP or HTTPS video feed. Connect only to a camera you can access.")
        side.addWidget(self.stream_url)
        credentials = QHBoxLayout()
        credentials.setSpacing(6)
        self.stream_username = QLineEdit()
        self.stream_username.setPlaceholderText("Username, if needed")
        self.stream_password = QLineEdit()
        self.stream_password.setPlaceholderText("Password")
        self.stream_password.setEchoMode(QLineEdit.EchoMode.Password)
        credentials.addWidget(self.stream_username)
        credentials.addWidget(self.stream_password)
        side.addLayout(credentials)
        self.stream_note = label("Address and password stay in memory for this session. Press Start to connect.", "muted")
        self.stream_note.setWordWrap(True)
        side.addWidget(self.stream_note)
        self.network_setup_button = QPushButton("Find / connect CCTV…")
        self.network_setup_button.clicked.connect(self.open_network_setup)
        side.addWidget(self.network_setup_button)

        self.open_button = QPushButton("Import && analyze video…")
        self.open_button.setToolTip("Choose any local video, even during monitoring. A managed copy stays in data/videos.")
        self.open_button.clicked.connect(self.choose_video)
        side.addWidget(self.open_button)
        self.library_combo = QComboBox()
        self.library_combo.setMinimumContentsLength(12)
        self.library_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.library_combo.activated.connect(self._select_library_video)
        side.addWidget(self.library_combo)
        self.file_label = label("Choose or drop a video at any time", "muted")
        self.file_label.setWordWrap(True)
        side.addWidget(self.file_label)
        self.import_status = label("", "muted")
        self.import_status.setWordWrap(True)
        self.import_status.hide()
        side.addWidget(self.import_status)
        import_row = QHBoxLayout()
        self.import_progress = QProgressBar()
        self.import_progress.setRange(0, 100)
        self.import_progress.setValue(0)
        self.import_progress.setTextVisible(True)
        self.import_progress.hide()
        self.cancel_import_button = QPushButton("Cancel")
        self.cancel_import_button.clicked.connect(self.cancel_import)
        self.cancel_import_button.hide()
        import_row.addWidget(self.import_progress, 1)
        import_row.addWidget(self.cancel_import_button)
        side.addLayout(import_row)

        side.addSpacing(3)
        self.start_button = QPushButton("Start monitoring")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_monitoring)
        side.addWidget(self.start_button)
        self.stop_button = QPushButton("Stop monitoring")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_monitoring)
        side.addWidget(self.stop_button)
        side.addSpacing(8)
        side.addWidget(label("DETECTION", "sectionTitle"))
        self.model_combo = QComboBox()
        for profile in MODEL_PROFILES:
            self.model_combo.addItem(profile.title, profile.model_path)
        selected_model = self.model_combo.findData(self.config.model_path)
        if selected_model < 0:
            self.model_combo.addItem(Path(self.config.model_path).name, self.config.model_path)
            selected_model = self.model_combo.count() - 1
        self.model_combo.setCurrentIndex(selected_model)
        self.model_combo.currentIndexChanged.connect(self._model_selection_changed)
        side.addWidget(self.model_combo)
        self.catalog_button = QPushButton("Browse supported categories…")
        self.catalog_button.clicked.connect(self.open_catalog)
        side.addWidget(self.catalog_button)
        self.model_note = label("", "muted")
        self.model_note.setWordWrap(True)
        side.addWidget(self.model_note)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All supported objects", "People and bags only", "Safety equipment and tools"])
        self.filter_combo.currentIndexChanged.connect(self._options_changed)
        side.addWidget(self.filter_combo)
        size_row = QHBoxLayout()
        size_row.addWidget(label("Inference size"))
        self.resolution_combo = QComboBox()
        sizes = sorted({320, 480, 640, self.config.image_size})
        for size in sizes:
            self.resolution_combo.addItem(str(size), size)
        self.resolution_combo.setCurrentIndex(self.resolution_combo.findData(self.config.image_size))
        self.resolution_combo.setToolTip("Smaller inputs are faster, but can miss small or distant objects.")
        self.resolution_combo.currentIndexChanged.connect(self._options_changed)
        size_row.addWidget(self.resolution_combo)
        side.addLayout(size_row)
        confidence_row = QHBoxLayout()
        confidence_row.addWidget(label("Confidence threshold"))
        confidence_row.addStretch()
        self.confidence_label = label(f"{self.config.confidence:.0%}", "sourceName")
        confidence_row.addWidget(self.confidence_label)
        side.addLayout(confidence_row)
        self.confidence_slider = QSlider(Qt.Orientation.Horizontal)
        self.confidence_slider.setRange(5, 95)
        self.confidence_slider.setValue(round(self.config.confidence * 100))
        self.confidence_slider.valueChanged.connect(self._options_changed)
        side.addWidget(self.confidence_slider)
        self.boxes_toggle = QCheckBox("Bounding boxes")
        self.labels_toggle = QCheckBox("Object labels + confidence")
        self.ids_toggle = QCheckBox("Tracking IDs")
        for toggle in (self.boxes_toggle, self.labels_toggle, self.ids_toggle):
            toggle.setChecked(True)
            toggle.toggled.connect(self._annotations_changed)
            side.addWidget(toggle)
        side.addSpacing(8)
        side.addWidget(label('POSSIBLE HAZARDS · V0.2', 'sectionTitle'))
        self.hazards_toggle = QCheckBox('Analyze possible hazards')
        self.hazards_toggle.toggled.connect(self._hazard_options_changed)
        side.addWidget(self.hazards_toggle)
        self.incident_record_toggle = QCheckBox('Save incident metadata locally')
        self.evidence_toggle = QCheckBox('Save incident evidence snapshots')
        self.evidence_toggle.setEnabled(False)
        self.audio_toggle = QCheckBox('Optional alert sound')
        self.desktop_toggle = QCheckBox('Local desktop notifications')
        for toggle in (self.incident_record_toggle,self.evidence_toggle,self.audio_toggle,self.desktop_toggle):
            toggle.toggled.connect(self._hazard_options_changed)
            side.addWidget(toggle)
        self.test_sound_button = QPushButton('Test enabled sound')
        self.test_sound_button.clicked.connect(self._test_sound)
        side.addWidget(self.test_sound_button)
        note = label('Unverified visual candidates only. Recording / sound start off. Evidence is owner-only, plaintext and retained for the configured period. Configure models and temporal rules in Operator center.', 'muted')
        note.setWordWrap(True);side.addWidget(note)
        side.addWidget(label("LOCAL METADATA", "sectionTitle"))
        self.metadata_toggle = QCheckBox("Record detection metadata")
        self.metadata_toggle.setChecked(False)
        self.metadata_toggle.toggled.connect(self._options_changed)
        side.addWidget(self.metadata_toggle)
        retention = label(f"Off by default. Samples every {self.config.sample_interval_s:g}s; retained for {self.config.retention_days} days, with a {self.config.max_detection_rows:,} row cap. No video or audio is recorded.", "muted")
        retention.setWordWrap(True)
        side.addWidget(retention)
        side.addStretch()
        privacy = label("ON-DEVICE PROCESSING\nNo face recognition. No identity inference.\nDetections require human interpretation.", "muted")
        privacy.setWordWrap(True)
        side.addWidget(privacy)
        body.addWidget(sidebar)

        main = QVBoxLayout()
        main.setSpacing(12)
        source_row = QHBoxLayout()
        source_row.addWidget(label("VISION FEED", "sectionTitle"))
        source_row.addStretch()
        self.source_name = label("No source active", "muted")
        self.source_name.setMaximumWidth(700)
        source_row.addWidget(self.source_name)
        main.addLayout(source_row)
        self.error_banner = label("", "banner")
        self.error_banner.setWordWrap(True)
        self.error_banner.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_banner.hide()
        main.addWidget(self.error_banner)
        self.incident_banner = label('', 'incidentBanner')
        self.incident_banner.setWordWrap(True)
        self.incident_banner.setStyleSheet('color:#f4d38c; background:#2a2215; border:1px solid #715725; padding:10px; border-radius:5px;')
        self.incident_banner.hide();main.addWidget(self.incident_banner)
        self.quick_detection_button=QPushButton('Show all objects + enable weapon / fire models')
        self.quick_detection_button.clicked.connect(self.enable_all_detection);main.addWidget(self.quick_detection_button)
        self.detection_mode_label=label('Ordinary object detection · hazard models off','muted')
        self.detection_mode_label.setWordWrap(True);main.addWidget(self.detection_mode_label)
        self.threat_label = label('Possible hazard analysis is off.', 'muted')
        self.threat_label.setWordWrap(True);main.addWidget(self.threat_label)
        self.video_panel = VideoPanel()
        main.addWidget(self.video_panel, 1)
        playback_row = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.toggle_pause)
        playback_row.addWidget(self.pause_button)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setEnabled(False)
        self.seek_slider.sliderReleased.connect(self._seek_released)
        self.seek_slider.sliderMoved.connect(self._seek_preview)
        playback_row.addWidget(self.seek_slider, 1)
        self.playback_label = label("LIVE / no video selected", "muted")
        self.playback_label.setMinimumWidth(110)
        playback_row.addWidget(self.playback_label)
        main.addLayout(playback_row)
        feed_footer = QHBoxLayout()
        self.connection_label = label("Standby · camera inactive", "muted")
        self.frame_label = label("No frames processed", "muted")
        feed_footer.addWidget(self.connection_label)
        feed_footer.addStretch()
        feed_footer.addWidget(self.frame_label)
        main.addLayout(feed_footer)
        self.statistics = StatisticsPanel()
        main.addWidget(self.statistics)
        note = label("Drop a video to import and analyze it. Tracking IDs can change after occlusion; they do not identify people.", "muted")
        note.setWordWrap(True)
        main.addWidget(note)
        body.addLayout(main, 1)
        page.addLayout(body, 1)
        self._source_type_changed()
        self._model_selection_changed()

    def _wall_monitoring(self):
        return self._camera_wall is not None and not self._camera_wall._closed and self._camera_wall.is_monitoring

    def open_camera_wall(self):
        if self._closing:return
        if self._camera_registry is None:
            from sentinal.storage.camera_registry import CameraRegistry
            self._camera_registry=CameraRegistry()
        if self._camera_wall is None or self._camera_wall._closed:
            from sentinal.interface.camera_wall import CameraWallDialog
            if self._camera_wall is not None:self._camera_wall.deleteLater()
            self._camera_wall=CameraWallDialog(self,self._camera_registry)
            self._camera_wall.activity_changed.connect(self._sync_wall_activity)
            self._camera_wall.setup_finished.connect(self._finish_close_if_ready)
        self._camera_wall.show();self._camera_wall.raise_();self._camera_wall.refresh()

    def _use_camera_group(self,selections):
        self.open_camera_wall()
        if self._camera_wall is not None:self._camera_wall.set_selections(selections)

    def _sync_wall_activity(self):
        active=self._wall_monitoring()
        if self._edge_bridge is not None:self._edge_bridge._send_heartbeat()
        self.model_combo.setEnabled(not self._camera_permission.pending and not active and not self._busy and not self._closing)
        self.start_button.setEnabled(not self._camera_permission.pending and not active and not self._busy and not self._closing and not self._worker_dead)
        if self._camera_manager_dialog is not None:self._camera_manager_dialog.set_monitoring_active(self._camera_permission.pending or self._busy or active)
        if not self._busy and not self._camera_permission.pending:
            self.status_chip.setText('●  MULTI-CAMERA' if active else '●  STANDBY')
            self.connection_label.setText('Monitoring in the multi-camera window' if active else 'No single source active')

    def enable_all_detection(self):
        from dataclasses import replace
        self.filter_combo.setCurrentIndex(0)
        self.hazard_settings=replace(self.hazard_settings,detectors=('weapons','fire_smoke'),detect_fire=True,detect_smoke=True)
        self.hazards_toggle.setChecked(True);self._hazard_options_changed()

    def _refresh_detection_mode(self):
        if not hasattr(self,'detection_mode_label'):return
        s=self.hazard_settings
        models=', '.join(s.detectors) if self.hazards_toggle.isChecked() else 'off'
        self.detection_mode_label.setText(f'Object filter: {self.filter_combo.currentText()} · objects ≥{self.confidence_slider.value()}% · hazard boxes ≥{s.display_confidence:.0%} · alert threshold ≥{s.confidence:.0%} · hazard models: {models}')

    def open_connected_settings(self):
        if self._closing:return
        if self._edge_bridge is None:
            from sentinal.connected.integration import DesktopEdgeBridge
            self._edge_bridge=DesktopEdgeBridge(self)
            self._edge_bridge.set_health_provider(self._connected_health)
            self._edge_bridge.attach(self._ensure_incidents())
            self._edge_bridge.error.connect(self._show_error)
        if self._connected_dialog is None:
            from sentinal.interface.connected_dialog import ConnectedDialog
            self._connected_dialog=ConnectedDialog(self._edge_bridge,self)
        self._connected_dialog.show();self._connected_dialog.raise_()

    def _connected_health(self):
        # Only semantic identifiers and measured values; never stream URLs.
        from sentinal.connected.monitor import model_metadata
        from sentinal.vision.types import utc_now
        packets=[];cameras=[]
        wall=self._camera_wall
        if wall is not None and not wall._closed:
            for ident,tile in wall.tiles.items():
                packet=tile.last_packet
                cameras.append({'camera_id':ident,'name':tile.name.text(),'status':wall.states.get(ident,'idle'),**({'last_frame_at':packet.timestamp} if packet else {})})
                if packet is not None:packets.append(packet)
        if self._current_spec is not None and not self._wall_monitoring():
            # The displayed source label may contain a URL; use a private-safe name.
            name=self._registry_selection.record.name if self._registry_selection is not None else 'Selected local source'
            packet=self.last_packet
            cameras.append({'camera_id':self._active_source_id,'name':name,'status':self._state,**({'last_frame_at':packet.timestamp} if packet else {})})
            if packet is not None:packets.append(packet)
        wall_states=set(wall.states.values()) if wall is not None and not wall._closed else set()
        active=self._state=='running' or 'running' in wall_states
        reconnecting=self._state in ('loading','reconnecting') or bool(wall_states & {'loading','connecting','reconnecting'})
        health={'status':'running' if active else 'reconnecting' if reconnecting else 'error' if self._state=='error' else 'idle'}
        if active and packets:
            latest=max(packets,key=lambda value:value.timestamp)
            health.update(processing_fps=latest.fps,inference_ms=latest.inference_ms)
            memory=latest.diagnostics.get('memory_rss_mb')
            if isinstance(memory,(int,float)):health['memory_rss_mb']=memory
        models={}
        for packet in packets:
            for model in model_metadata(packet.detector_health):
                if not active:model={**model,'status':'idle'}
                models[model['model_id']]=model
        return {'health':health,'cameras':cameras[:32],'models':list(models.values())[:16]}

    def _ensure_incidents(self):
        if self._incident_worker is None:
            from sentinal.core.incident_worker import IncidentWorker
            self._incident_worker = IncidentWorker(self)
            self._incident_worker.incident_changed.connect(self._incident_changed)
            self._incident_worker.error.connect(self._incident_error)
            self._incident_worker.finished.connect(self._finish_close_if_ready)
            self._incident_worker.start()
        return self._incident_worker

    def open_control_center(self):
        if self._closing:return
        if self._control_center is None:
            from sentinal.interface.control_center import ControlCenter
            self._control_center = ControlCenter(self._ensure_incidents(),self.hazard_settings,self)
            self._control_center.settings_applied.connect(self._hazard_settings_applied)
            self._control_center.cameras_requested.connect(self.open_camera_manager)
        self._refresh_control_center(force=True)
        self._control_center.show();self._control_center.raise_();self._control_center.activateWindow()

    def open_camera_manager(self):
        if self._closing:return
        try:
            if self._camera_registry is None:
                from sentinal.storage.camera_registry import CameraRegistry
                self._camera_registry = CameraRegistry()
            if self._camera_manager_dialog is None:
                from sentinal.interface.camera_manager_dialog import CameraManagerDialog
                self._camera_manager_dialog = CameraManagerDialog(self,registry=self._camera_registry)
                self._camera_manager_dialog.camera_selected.connect(self._use_registered_camera)
                self._camera_manager_dialog.cameras_selected.connect(self._use_camera_group)
                self._camera_manager_dialog.setup_finished.connect(self._finish_close_if_ready)
            self._camera_manager_dialog.set_monitoring_active(self._busy or self._wall_monitoring())
            self._camera_manager_dialog.show();self._camera_manager_dialog.raise_()
        except Exception:self._show_error('Camera settings are unavailable. Check local permissions; direct source selection can still be used.')

    def _use_registered_camera(self,selection):
        if self._busy or self._closing:return
        if selection.spec.kind == 'stream':
            self._use_network_stream(selection.endpoint,selection.username,selection.password)
        else:
            self.refresh_cameras()
            index = next((i for i in range(self.camera_combo.count()) if getattr(self.camera_combo.itemData(i),'device_id',None)==selection.spec.camera_device_id),-1)
            if index<0:
                self._show_error('The selected named camera is unavailable. No replacement will open.');return
            self.source_type.setCurrentIndex(0);self.camera_combo.setCurrentIndex(index)
        self._registry_selection=selection
        self.connection_label.setText('Selected '+selection.record.name+' · press Start monitoring to connect.')

    def _wire_incident_consumer(self):
        if not hasattr(self.worker,'set_incident_consumer'):return
        if self.hazards_toggle.isChecked():
            service=self._ensure_incidents();source_id=self._active_source_id
            self.worker.set_incident_consumer(lambda packet,owner=service,ident=source_id:owner.submit_packet(packet,ident))
        else:self.worker.set_incident_consumer(None)

    def _apply_hazard_options(self):
        if not hasattr(self,'worker') or not hasattr(self.worker,'set_hazard_options'):return
        s=self.hazard_settings
        self.worker.set_hazard_options(enabled=s.detectors if self.hazards_toggle.isChecked() else (),confidence=s.display_confidence,image_size=int(self.resolution_combo.currentData()),sample_interval_s=s.sample_interval_s,detect_fire=s.detect_fire,detect_smoke=s.detect_smoke,category_thresholds=s.category_thresholds)

    def _hazard_options_changed(self,*_):
        if not hasattr(self,'worker'):return
        persist=self.incident_record_toggle.isChecked()
        self.evidence_toggle.setEnabled(persist)
        if not persist and self.evidence_toggle.isChecked():
            with QSignalBlocker(self.evidence_toggle):self.evidence_toggle.setChecked(False)
        if self.hazards_toggle.isChecked() or persist or self._incident_worker is not None:
            signature=(self.hazard_settings,persist,self.evidence_toggle.isChecked())
            if signature!=self._incident_options_signature:
                self._ensure_incidents().configure(self.hazard_settings,persist=persist,snapshots=self.evidence_toggle.isChecked())
                self._incident_options_signature=signature
        self._wire_incident_consumer();self._apply_hazard_options()
        self._refresh_detection_mode()
        if self._camera_wall is not None and not self._camera_wall._closing:self._camera_wall.apply_options()
        if not self.hazards_toggle.isChecked():self.threat_label.setText('Possible hazard analysis is off.')
        elif not ('weapons' in self.hazard_settings.detectors or ('fire_smoke' in self.hazard_settings.detectors and (self.hazard_settings.detect_fire or self.hazard_settings.detect_smoke))):
            self.threat_label.setText('No hazard detectors enabled. Choose models in Operator center.')
        if self.audio_toggle.isChecked() or self.desktop_toggle.isChecked() or self._alert_output is not None:
            if self._alert_output is None:
                from sentinal.interface.local_alerts import LocalAlertOutput
                self._alert_output=LocalAlertOutput(self);self._alert_output.delivery.connect(self._alert_delivery)
            s=self.hazard_settings
            self._alert_output.configure(audio=self.audio_toggle.isChecked(),desktop=self.desktop_toggle.isChecked(),volume=s.audio_volume,severity=s.audio_severity)

    def _hazard_settings_applied(self,settings):
        self.hazard_settings=settings;self._hazard_options_changed()

    def _incident_error(self,message):
        if self.incident_record_toggle.isChecked() and (self._incident_worker is None or not self._incident_worker.persist):
            with QSignalBlocker(self.incident_record_toggle):self.incident_record_toggle.setChecked(False)
            with QSignalBlocker(self.evidence_toggle):self.evidence_toggle.setChecked(False)
            self.evidence_toggle.setEnabled(False)
            self._hazard_options_changed()
        self._show_error(message)

    def _incident_changed(self,row):
        self._last_incident=row
        if row['status']=='ALERTED':
            self._banner_incident_id=row['incident_id']
            category=row['category'].replace('weapon_','').replace('_',' ')
            source=self.source_name.text() if row['source_id']==self._active_source_id else row['source_id']
            if self._camera_wall is not None and row['source_id'] in self._camera_wall.tiles:source=self._camera_wall.tiles[row['source_id']].name.text()
            self.incident_banner.setText(f"POSSIBLE {category.upper()} · {row['confidence']:.0%} · Source {source}\nAwaiting human verification · {row['last_seen']} · Open Operator center to review.")
            self.incident_banner.show()
            if self._alert_output is not None:self._alert_output.send(row)
        elif row['status'] in {'ACKNOWLEDGED','VERIFIED','DISMISSED','CLOSED'} and row['incident_id']==self._banner_incident_id and self.incident_banner.isVisible():
            self.incident_banner.setText(f"INCIDENT {row['incident_id'][:8]} · {row['status']} · Human review recorded{' locally' if row.get('persistence_status')=='saved' else ' for this session'}.")

    def _alert_delivery(self,result):
        if self._incident_worker is not None:self._incident_worker.delivery(result['incident_id'],result['channel'],result['status'])

    def _test_sound(self):
        if not self.audio_toggle.isChecked():
            self._show_error('Enable Optional alert sound before testing it.');return
        self._hazard_options_changed()
        if not self._alert_output.test_sound():self._show_error('Local sound is not ready or no compatible output is available. Try again after loading.')

    def _update_camera_health(self,state,packet=None):
        if self._camera_registry is None or not self._registry_camera_id:return
        now=time.monotonic()
        if packet is not None and now-self._last_camera_health<1:return
        self._last_camera_health=now
        connection={'loading':'connecting','running':'online','paused':'online','reconnecting':'reconnecting','stopped':'stopped','eof':'stopped','error':'error'}.get(state,'idle')
        ai='active' if state=='running' and packet is not None else 'paused' if state=='paused' else 'unavailable' if state=='reconnecting' else 'error' if state=='error' else 'idle'
        try:self._camera_registry.update_health(self._registry_camera_id,connection_health=connection,ai_status=ai,frame_timestamp=packet.timestamp if packet is not None else None)
        except Exception:self._show_error('Camera health could not be saved. Check local camera configuration permissions.')

    def _refresh_control_center(self,packet=None,force=False):
        if self._control_center is None:return
        now=time.monotonic()
        if not force and now-self._last_runtime_refresh<.5:return
        self._last_runtime_refresh=now
        cameras=self._camera_registry.list_cameras() if self._camera_registry is not None else ()
        wall=self._camera_wall
        wall_active=self._wall_monitoring()
        self._control_center.current_source='' if wall_active else self._active_source_id
        self._control_center.camera_override.setEnabled(not wall_active)
        if wall_active:
            self._control_center.camera_override.setChecked(False)
            packets=[tile.last_packet for tile in wall.tiles.values() if tile.last_packet is not None]
            recent=max(packets,key=lambda item:item.timestamp) if packets else None
            self._control_center.update_runtime('running' if recent else 'loading','Multi-camera monitor (per-camera health below)',recent,cameras)
            self._control_center.current_source=''
        else:self._control_center.update_runtime(self._state,self.source_name.text(),packet,cameras)

    def _camera_selection_changed(self, *_):
        self._invalidate_camera_permission()
        device = self.camera_combo.currentData()
        if device is not None:
            self._selected_camera_id = device.device_id

    def _invalidate_camera_permission(self,*_):
        self._camera_permission.cancel()

    def _camera_permission_changed(self,pending):
        if not hasattr(self,'start_button') or self._closing:return
        self._set_busy(self._busy)
        if pending:
            self.status_chip.setText('●  CAMERA PERMISSION')
            self.connection_label.setText('Waiting for your macOS camera permission decision · Stop cancels this monitoring request')
        elif not self._busy and not self._wall_monitoring():
            self.status_chip.setText('●  STANDBY')
            self.connection_label.setText('No camera source active')

    def _refresh_after_camera_permission(self):
        if self._closing or self._busy or self._wall_monitoring():return
        # A newly visible device is never silently selected after granting access.
        self._camera_initialized=True
        self.refresh_cameras()
        self.connection_label.setText('Camera access allowed. Select the exact camera, then press Start. No camera was opened.')
        self.camera_note.setText('Select the exact Mac or iPhone camera and press Start; permission alone does not activate it.')

    def _refresh_after_camera_start_consent(self):
        self._refresh_after_camera_permission()
        if not self._closing and self.camera_combo.currentData() is None:
            self._show_error('Select the exact camera before starting monitoring. Camera access is allowed; no camera has been opened.')

    def request_camera_refresh(self):
        if self._closing or self._busy or self._wall_monitoring():return
        self._camera_permission.ensure(self,self._refresh_after_camera_permission)

    def refresh_cameras(self):
        previous = self._selected_camera_id
        devices = discover_cameras()
        with QSignalBlocker(self.camera_combo):
            self.camera_combo.clear()
            self.camera_combo.addItem("Choose a camera…", None)
            for device in devices:
                self.camera_combo.addItem(f"{device.category} · {device.name}", device)
            selected = next((i + 1 for i, d in enumerate(devices) if d.device_id == previous), 0)
            if not self._camera_initialized and previous is None:
                selected = next((i + 1 for i, d in enumerate(devices) if d.is_builtin), 0)
                if selected:
                    self._selected_camera_id = devices[selected - 1].device_id
            self.camera_combo.setCurrentIndex(selected)
        self._camera_initialized = True
        if previous and not selected and self._camera_permission.pending_for(self):
            self._camera_permission.cancel(self)
        if previous and not selected:
            self.camera_note.setText("The selected camera is unavailable. Reconnect it or explicitly choose another; no replacement will open.")
        elif not devices:
            self.camera_note.setText("No camera is available. Connect one, allow camera access and refresh. No default camera will be opened.")
        else:
            self.camera_note.setText("Exact-device selection. Stop, choose Mac or iPhone, then Start. A missing camera never switches to another.")

    def open_network_setup(self):
        if self._busy or self._closing:
            return
        if self._network_dialog is None:
            self._network_dialog = NetworkCameraDialog(self)
            self._network_dialog.stream_selected.connect(self._use_network_stream)
            self._network_dialog.setup_finished.connect(self._finish_close_if_ready)
        self._network_dialog.show()
        self._network_dialog.raise_()
        self._network_dialog.activateWindow()

    def _use_network_stream(self, url, username, password):
        if self._busy or self._closing:
            return
        self.source_type.setCurrentIndex(2)
        self.stream_url.setText(url)
        self._credential_endpoint = None
        self._normalize_stream_fields()
        self.stream_username.setText(username)
        self.stream_password.setText(password)
        self.stream_note.setText("Camera stream selected. Press Start monitoring to connect and analyze it.")

    def open_catalog(self):
        CatalogDialog(self.model_combo.currentData(), self).exec()

    def _model_selection_changed(self, *_):
        if not hasattr(self, "model_note"):
            return
        path = self.model_combo.currentData()
        rows = catalog_rows(path)
        safety = sum(row["safety_tool"] for row in rows)
        installed = (ROOT / path).is_file()
        self.model_note.setText(f"{len(rows)} permitted categories · {safety} safety / tool categories. " + ("Loaded on Start; change model while stopped." if installed else "Weights missing: run install.command before starting.") + (" Safety/tool recognition is experimental; review every result." if safety > 2 else ""))
        if hasattr(self, "worker"):
            self._options_changed()

    def refresh_library(self, select_path=None):
        selected = str(select_path or self.video_path or "")
        with QSignalBlocker(self.library_combo):
            self.library_combo.clear()
            self.library_combo.addItem("Imported video library…", None)
            try:
                entries = self.video_library.list_entries()
            except Exception:
                self._show_error("The imported video library could not be read. You can still import a video or open a local source.")
                entries = []
            self._video_names = {str(entry.path): entry.display_name for entry in entries}
            for entry in entries:
                path = str(entry.path)
                self.library_combo.addItem(entry.display_name, path)
                if path == selected:
                    self.library_combo.setCurrentIndex(self.library_combo.count() - 1)

    def choose_video(self):
        if self._closing or self._import_worker is not None:
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Import and analyze a local video", str(ROOT / "data/videos"), "Video files (*.mp4 *.mov *.m4v *.avi *.mkv *.webm *.mpeg *.mpg *.ts);;All files (*)")
        if filename:
            self.start_video_import(filename)

    def start_video_import(self, filename):
        if self._closing:
            return
        if self._import_worker is not None:
            self._show_error("A video is already being imported. Wait for it or cancel the import first.")
            return
        self.error_banner.hide()
        self.import_status.setText("Importing video into the project…")
        self.import_status.show()
        self.import_progress.setValue(0)
        self.import_progress.show()
        self.cancel_import_button.setEnabled(True)
        self.cancel_import_button.show()
        self._import_worker = VideoImportWorker(filename, parent=self, library=self.video_library)
        self._import_worker.progress.connect(self._on_import_progress)
        self._import_worker.imported.connect(self._on_imported)
        self._import_worker.failed.connect(self._on_import_failed)
        self._import_worker.cancelled.connect(self._on_import_cancelled)
        self._import_worker.finished.connect(self._on_import_finished)
        self._update_import_controls()
        self._import_worker.start()

    def begin_video_import(self, filename):
        """Public import entry point shared by file selection, drop and verification."""
        self.start_video_import(filename)

    def cancel_import(self):
        if self._import_worker is not None:
            self.cancel_import_button.setEnabled(False)
            self.import_status.setText("Cancelling import safely…")
            self._import_worker.cancel()

    def _on_import_progress(self, processed, total):
        total = max(0, int(total))
        processed = max(0, int(processed))
        self.import_progress.setValue(min(100, round(processed * 100 / total)) if total else 0)
        self.import_status.setText(f"Importing · {processed / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB")

    def _on_imported(self, entry):
        self.refresh_library(entry.path)
        self.import_progress.setValue(100)
        self.import_status.setText(f"Ready · {entry.display_name}")
        if not self._closing:
            self.analyze_video(entry.path)

    def _on_import_failed(self, message):
        self.import_status.setText("Import could not complete. Monitoring can continue.")
        if not self._closing:
            self._show_error(message)

    def _on_import_cancelled(self):
        self.import_status.setText("Import cancelled. The current source was not changed.")

    def _on_import_finished(self):
        worker, self._import_worker = self._import_worker, None
        if worker is not None:
            worker.deleteLater()
        self.import_progress.hide()
        self.cancel_import_button.hide()
        self._update_import_controls()
        self._finish_close_if_ready()

    def _update_import_controls(self):
        available = not self._closing and not self._worker_dead and self._import_worker is None
        self.open_button.setEnabled(available)
        self.library_combo.setEnabled(not self._closing and not self._worker_dead)
        self.setAcceptDrops(available)

    def _select_library_video(self, index):
        path = self.library_combo.itemData(index)
        if path and not self._closing:
            self.analyze_video(path)

    def analyze_video(self, filename):
        """An explicit import/drop/library action can switch a running source safely."""
        path = str(Path(filename).expanduser().resolve())
        if self._closing:
            return
        if self._busy:
            self._pending_video_path = path
            self.connection_label.setText("Video ready · stopping the current source before switching…")
            self.stop_monitoring()
            return
        self.load_video(path)
        self.start_monitoring()

    def load_video(self, filename):
        """Preselect a path without importing or starting it (CLI and integration API)."""
        self.video_path = str(Path(filename).expanduser().resolve())
        self.file_label.setText(self._video_display_name(self.video_path))
        self.file_label.setToolTip(self.video_path)
        self.source_type.setCurrentIndex(1)
        self._source_type_changed()
        if hasattr(self, "library_combo"):
            with QSignalBlocker(self.library_combo):
                index = self.library_combo.findData(self.video_path)
                if index >= 0:
                    self.library_combo.setCurrentIndex(index)

    def _video_display_name(self, filename):
        return getattr(self, "_video_names", {}).get(str(filename), Path(filename).name)

    def _source_type_changed(self, *_):
        pending=self._camera_permission.pending
        is_camera = self.source_type.currentIndex() == 0
        is_stream = self.source_type.currentIndex() == 2
        self.camera_combo.setEnabled(is_camera and not pending and not self._busy and not self._closing)
        self.refresh_button.setEnabled(is_camera and not pending and not self._busy and not self._closing)
        for widget in (self.stream_url, self.stream_username, self.stream_password):
            widget.setVisible(is_stream)
            widget.setEnabled(is_stream and not self._busy and not self._closing)
        self.stream_note.setVisible(is_stream)
        self.camera_note.setVisible(is_camera)
        self.camera_combo.setVisible(is_camera)
        self.refresh_button.setVisible(is_camera)
        self.network_setup_button.setVisible(is_stream)
        self.network_setup_button.setEnabled(is_stream and not self._busy and not self._closing)
        self.start_button.setText("Start monitoring")
        if not self._busy and self._state != "eof":
            self._on_playback({"duration_s": 0, "position_s": 0, "can_seek": False})

    def _normalize_stream_fields(self):
        """Move URL userinfo into masked credential fields without writing it to disk."""
        raw = self.stream_url.text().strip()
        try:
            parts = urlsplit(raw)
            if not parts.hostname:
                return
            endpoint = (parts.scheme.lower(), parts.hostname, parts.port)
            if self._credential_endpoint is not None and endpoint != self._credential_endpoint:
                self.stream_username.clear()
                self.stream_password.clear()
            if parts.username is not None:
                self.stream_username.setText(unquote(parts.username))
                self.stream_password.setText(unquote(parts.password or ""))
            self._credential_endpoint = endpoint
            hostname = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
            netloc = hostname + (f":{parts.port}" if parts.port else "")
            self.stream_url.setText(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))
        except ValueError:
            return

    def _stream_spec(self):
        self._normalize_stream_fields()
        raw = self.stream_url.text().strip()
        if not raw:
            raise ValueError("Enter your camera's RTSP or HTTP video address before starting.")
        parts = urlsplit(raw)
        if not parts.hostname:
            raise ValueError("Enter a valid RTSP, RTSPS, HTTP or HTTPS video address.")
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        netloc = host + (f":{parts.port}" if parts.port else "")
        username, password = self.stream_username.text(), self.stream_password.text()
        if username or password:
            netloc = quote(username, safe="") + (":" + quote(password, safe="") if password else "") + "@" + netloc
        return SourceSpec("stream", urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))

    def start_monitoring(self):
        if self._busy or self._closing or self._camera_permission.pending:
            return
        if self._wall_monitoring():
            self._show_error('Stop the camera wall before starting a separate single source.');return
        if self._worker_dead or not self.worker.isRunning():
            self._show_error("The vision worker is unavailable. Close and reopen SENTINAL before monitoring.")
            return
        try:
            if self.source_type.currentIndex() == 1:
                if not self.video_path:
                    self._show_error("Choose a local video file before starting monitoring.")
                    return
                spec = SourceSpec("file", self.video_path)
                source_text = self._video_display_name(self.video_path)
            elif self.source_type.currentIndex() == 2:
                spec = self._stream_spec()
                source_text = spec.description
            else:
                device = self.camera_combo.currentData()
                if device is None or not device.device_id:
                    self._camera_permission.ensure(self,self._refresh_after_camera_start_consent)
                    return
                spec = SourceSpec("camera", device.index, camera_device_id=device.device_id, camera_name=device.name)
                source_text = self.camera_combo.currentText()
        except (ValueError, TypeError):
            self._show_error("Enter a valid RTSP, RTSPS, HTTP or HTTPS video address and check its port. No connection has been started.")
            return
        if spec.kind=='camera':
            self._camera_permission.ensure(self,lambda:self._start_permitted_camera(spec,source_text))
            return
        self._begin_monitoring(spec,source_text)

    def _start_permitted_camera(self,spec,source_text):
        if self._closing or self._busy or self._wall_monitoring() or self.source_type.currentIndex()!=0:return
        current=self.camera_combo.currentData()
        if current is None or current.device_id!=spec.camera_device_id:return
        self.refresh_cameras()
        current=self.camera_combo.currentData()
        if current is None or current.device_id!=spec.camera_device_id:
            self._show_error('The selected camera changed or disappeared while permission was checked. Select it explicitly and press Start again. No other camera was opened.');return
        self._begin_monitoring(spec,source_text)

    def _begin_monitoring(self,spec,source_text):
        if self._closing or self._busy or self._wall_monitoring():return
        self._current_spec = spec
        selection = self._registry_selection
        self._registry_camera_id = selection.record.camera_id if selection and selection.spec == spec else None
        raw_identity = spec.camera_device_id if spec.kind == 'camera' else str(spec.value)
        self._active_source_id = self._registry_camera_id or ('source-' + hashlib.sha256((spec.kind + ':' + raw_identity).encode()).hexdigest()[:24])
        self._wire_incident_consumer()
        self.source_name.setText(source_text)
        self.error_banner.hide()
        self.last_packet = None
        self.video_panel.clear_frame("PREPARING VISION CORE")
        self.statistics.reset_live()
        self.frame_label.setText("No frames processed in this session")
        self._playback = {"duration_s": 0.0, "position_s": 0.0, "can_seek": False}
        self._set_busy(True)
        self.status_chip.setText("●  STARTING")
        self.connection_label.setText("Opening source and preparing local inference…")
        self._options_changed()
        self.worker.request_start(spec)

    def stop_monitoring(self):
        if self._camera_permission.pending:
            self._camera_permission.cancel()
            self.connection_label.setText('Camera start cancelled. No monitoring began; finish any open macOS permission dialog before retrying.')
            return
        if self._busy:
            self.stop_button.setEnabled(False)
            self.pause_button.setEnabled(False)
            self.seek_slider.setEnabled(False)
            self.connection_label.setText("Stopping safely · waiting for current frame…")
            self.status_chip.setText("●  STOPPING")
            self.worker.request_stop()

    def _set_busy(self, busy):
        pending=self._camera_permission.pending
        self._busy = busy
        self.model_combo.setEnabled(not pending and not busy and not self._wall_monitoring() and not self._closing and not self._worker_dead)
        self.start_button.setEnabled(not pending and not busy and not self._wall_monitoring() and not self._closing and not self._worker_dead)
        self.stop_button.setEnabled((busy or pending) and not self._closing)
        self.source_type.setEnabled(not pending and not busy and not self._closing and not self._worker_dead)
        self._source_type_changed()
        self._update_import_controls()
        self.camera_manager_button.setEnabled(not busy and not self._closing)
        if self._camera_manager_dialog is not None:self._camera_manager_dialog.set_monitoring_active(pending or busy or self._wall_monitoring())
        is_file = self._current_spec is not None and self._current_spec.kind == "file"
        self.pause_button.setEnabled(busy and is_file and not self._closing and self._state in ("running", "paused"))
        self.seek_slider.setEnabled(busy and is_file and bool(self._playback.get("can_seek")) and not self._closing)

    def _on_state(self, state, message):
        self._state = state
        self._update_camera_health(state)
        self.connection_label.setText(message)
        chips = {"loading": "●  PREPARING", "running": "●  MONITORING", "paused": "●  PAUSED", "reconnecting": "●  RECONNECTING", "stopped": "●  STOPPED", "eof": "●  COMPLETE", "error": "●  SOURCE ERROR"}
        self.status_chip.setText(chips.get(state, "●  STANDBY"))
        self.status_chip.setStyleSheet("color: #f5bbc2; border-color: #694050; background: #331c25;" if state == "error" else "")
        self.pause_button.setText("Resume" if state == "paused" else "Pause")
        if state in ("running", "paused"):
            self._set_busy(True)
        elif state == "loading":
            self.pause_button.setEnabled(False)
            self.seek_slider.setEnabled(False)
        elif state == "reconnecting":
            self.pause_button.setEnabled(False)
            self.seek_slider.setEnabled(False)
            self.last_packet = None
            self.video_panel.clear_frame("RECONNECTING TO SOURCE")
            self.statistics.reset_live()
            self.frame_label.setText("Waiting for fresh live frames…")
        if state in ('stopped','eof','error','paused','reconnecting'):
            self.statistics.reset_live()
            self.threat_label.setText('No current hazard analysis · ' + state + '. Incident history remains available for review.')
        self._refresh_control_center(force=True)
        if state in ("stopped", "eof", "error"):
            self._poll_frame()
            self.threat_label.setText('No current hazard analysis · ' + state + '. Incident history remains available for review.')
            self._set_busy(False)
            if state == "eof":
                self.start_button.setText("Replay video")
            if state in ("stopped", "error"):
                self.statistics.reset_live()
            if state == "error":
                self.video_panel.clear_frame("SOURCE UNAVAILABLE")
            if self._pending_video_path is not None and not self._closing:
                filename, self._pending_video_path = self._pending_video_path, None
                QTimer.singleShot(0, lambda path=filename: self.analyze_video(path))

        if self._edge_bridge is not None:self._edge_bridge._send_heartbeat()

    def _show_error(self, message):
        self.error_banner.setText(message)
        self.error_banner.show()

    def _metadata_error(self, message):
        with QSignalBlocker(self.metadata_toggle):
            self.metadata_toggle.setChecked(False)
        self._show_error(f"Metadata recording was disabled: {message} Video monitoring can continue.")

    def _options_changed(self, *_):
        if not hasattr(self, "confidence_slider"):
            return
        confidence = self.confidence_slider.value() / 100
        self.confidence_label.setText(f"{confidence:.0%}")
        if hasattr(self, "worker"):
            self.worker.set_options(confidence=confidence, focus_only=self.filter_combo.currentIndex() == 1, metadata_enabled=self.metadata_toggle.isChecked(), image_size=int(self.resolution_combo.currentData()), model_path=self.model_combo.currentData(), category_filter=("all", "focus", "safety")[self.filter_combo.currentIndex()])
            self._apply_hazard_options()
            self._refresh_detection_mode()
            if self._camera_wall is not None and not self._camera_wall._closing:self._camera_wall.apply_options()

    def _annotations_changed(self, *_):
        if hasattr(self, "video_panel"):
            self.video_panel.set_annotations(self.boxes_toggle.isChecked(), self.labels_toggle.isChecked(), self.ids_toggle.isChecked())

    def toggle_pause(self):
        if self._busy and self._current_spec is not None and self._current_spec.kind == "file":
            self.worker.request_pause(self._state != "paused")

    def _on_playback(self, info):
        self._playback = dict(info)
        duration = max(0.0, float(info.get("duration_s") or 0))
        position = max(0.0, float(info.get("position_s") or 0))
        is_file = self._current_spec is not None and self._current_spec.kind == "file"
        self.seek_slider.setEnabled(is_file and self._busy and bool(info.get("can_seek")) and not self._closing)
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(min(1000, round(position / duration * 1000)) if duration else 0)
        self.playback_label.setText(f"{clock_text(position)} / {clock_text(duration)}" if is_file else "LIVE")

    def _seek_preview(self, value):
        duration = float(self._playback.get("duration_s") or 0)
        self.playback_label.setText(f"{clock_text(duration * value / 1000)} / {clock_text(duration)}")

    def _seek_released(self):
        if self.seek_slider.isEnabled():
            duration = float(self._playback.get("duration_s") or 0)
            self.worker.request_seek(duration * self.seek_slider.value() / 1000)

    def _poll_frame(self):
        packet = self.worker.take_latest()
        if packet is None:
            return
        self.last_packet = packet
        if self._edge_bridge is not None and self._connected_session != packet.session_id:
            self._connected_session=packet.session_id;self._edge_bridge._send_heartbeat()
        self.video_panel.present_packet(packet,hazards_enabled=self.hazards_toggle.isChecked())
        if self._state=='running':self.statistics.update_packet(packet)
        else:self.statistics.reset_live()
        if getattr(packet,'hazard_sampled',False) and self._state=='running' and self.hazards_toggle.isChecked():
            descriptions = [h.category.replace('weapon_','').replace('_',' ') + f' {h.confidence:.0%}' for h in packet.hazards]
            unavailable=[name for name,health in packet.detector_health.items() if health.get('status')=='unavailable']
            if descriptions:self.threat_label.setText('POSSIBLE: ' + ', '.join(descriptions) + ' · ' + packet.timestamp)
            elif unavailable:self.threat_label.setText('Hazard analysis incomplete · unavailable: ' + ', '.join(unavailable) + ' · See Operator center diagnostics.')
            else:self.threat_label.setText('No possible hazards in the last analyzed sample · ' + packet.timestamp)
        self._update_camera_health(self._state,packet)
        self._refresh_control_center(packet)
        live = self._current_spec is not None and self._current_spec.kind in ("camera", "stream")
        self.frame_label.setToolTip("Age measures local frame read through completed detection/tracking. It excludes the remote camera encoder and upstream buffering. Skipped counts older locally captured frames omitted to keep analysis current." if live else "Original video frame index, media time and source resolution.")
        prefix = f"LIVE · age {getattr(packet, 'frame_age_ms', 0):.0f} ms · skipped {getattr(packet, 'dropped_frames', 0):,} · " if live else ""
        self.frame_label.setText(f"{prefix}Processed frame {packet.frame_index:,}   ·   {clock_text(packet.source_time_s)}   ·   {packet.frame.shape[1]} × {packet.frame.shape[0]}")

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if not self._closing and self._import_worker is None and len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if not self._closing and self._import_worker is None and len(urls) == 1 and urls[0].isLocalFile():
            self.start_video_import(urls[0].toLocalFile())
            event.acceptProposedAction()
        else:
            event.ignore()

    def closeEvent(self, event):
        self._camera_permission.cancel()
        wall_busy=self._camera_wall is not None and self._camera_wall.setup_running
        network_busy = self._network_dialog is not None and self._network_dialog.setup_running
        camera_busy = self._camera_manager_dialog is not None and self._camera_manager_dialog.setup_running
        incident_busy = self._incident_worker is not None and self._incident_worker.isRunning()
        if self.worker.isRunning() or self._import_worker is not None or network_busy or camera_busy or incident_busy or wall_busy:
            event.ignore()
            self._closing = True
            if self._edge_bridge is not None:self._edge_bridge.stop()
            if self._connected_dialog is not None:self._connected_dialog.hide()
            self._pending_video_path = None
            self._set_busy(True)
            self.stop_button.setEnabled(False)
            self.status_chip.setText('●  CLOSING')
            self.connection_label.setText('Releasing sources, inference and local records…')
            self.cancel_import()
            for dialog in (self._network_dialog,self._camera_manager_dialog):
                if dialog is not None:dialog.close();dialog.cancel_setup()
            if self._camera_wall is not None:self._camera_wall.close()
            if self._control_center is not None:self._control_center.hide()
            if hasattr(self.worker,'set_incident_consumer'):self.worker.set_incident_consumer(None)
            self.worker.request_shutdown()
            if self._incident_worker is not None:self._incident_worker.request_shutdown()
            if self._alert_output is not None:self._alert_output.close()
            self.stream_password.clear()
        else:
            self._timer.stop()
            self._cleanup_v02()
            event.accept()

    def _cleanup_v02(self):
        if self._edge_bridge is not None:self._edge_bridge.close(timeout=5)
        if self._connected_dialog is not None:self._connected_dialog.hide()
        if self._alert_output is not None:self._alert_output.close()
        if self._camera_registry is not None:
            self._camera_registry.close();self._camera_registry=None
        self._registry_selection=None

    def _finish_close_if_ready(self):
        wall_busy=self._camera_wall is not None and self._camera_wall.setup_running
        network_busy = self._network_dialog is not None and self._network_dialog.setup_running
        camera_busy = self._camera_manager_dialog is not None and self._camera_manager_dialog.setup_running
        incident_busy = self._incident_worker is not None and self._incident_worker.isRunning()
        if self._closing and not self.worker.isRunning() and self._import_worker is None and not network_busy and not camera_busy and not incident_busy and not wall_busy:
            self.close()

    def _worker_finished(self):
        if self._closing:
            self._finish_close_if_ready()
        else:
            self._worker_dead = True
            self._pending_video_path = None
            self._on_state('error','Monitoring unavailable · vision worker stopped and source released')
            self._show_error("The vision worker stopped. Close and reopen SENTINAL to resume.")
