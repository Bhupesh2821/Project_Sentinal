"""Operator controls for uncertain observations, local review and measured health."""
from dataclasses import replace
import json
from PySide6.QtCore import Qt, Signal, QDateTime, QTimeZone
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog,QTabWidget,QWidget,QVBoxLayout,QHBoxLayout,
    QLabel,QPushButton,QTableWidget,QTableWidgetItem,QLineEdit,QComboBox,
    QDoubleSpinBox,QSpinBox,QCheckBox,QFormLayout,QPlainTextEdit,QScrollArea,
    QMessageBox,QDateTimeEdit)
from sentinal.core.v02_settings import V02Settings
from sentinal.core.incidents import TRANSITIONS


def caption(text):
    widget=QLabel(text);widget.setWordWrap(True);return widget

class ControlCenter(QDialog):
    settings_applied=Signal(object)
    cameras_requested=Signal()
    def __init__(self,service,settings,parent=None):
        super().__init__(parent)
        self.service=service;self.settings=settings;self.rows=[];self.current_source='';self._last_diagnostic={}
        self.setWindowTitle('SENTINAL · Operator Center');self.resize(1090,760)
        layout=QVBoxLayout(self)
        layout.addWidget(caption('Possible hazards require human review. Model confidence is not a measure of danger.'))
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        self._overview();self._incidents();self._settings();self._diagnostics()
        service.records_changed.connect(self.show_records)
        service.incident_changed.connect(self.incident_changed)
        service.audit_ready.connect(self.show_audit)
        service.evidence_ready.connect(self.show_evidence)
        footer=QHBoxLayout();footer.addStretch()
        live=QPushButton('Return to live monitoring');live.clicked.connect(self.hide)
        footer.addWidget(live);layout.addLayout(footer)
    def _page(self,title):
        widget=QWidget();layout=QVBoxLayout(widget);self.tabs.addTab(widget,title);return layout
    def _overview(self):
        page=self._page('Overview / Cameras')
        self.summary=caption('Standby · no source is being monitored.');page.addWidget(self.summary)
        self.ai_health=QPlainTextEdit();self.ai_health.setReadOnly(True);page.addWidget(self.ai_health)
        page.addWidget(caption('Named cameras use exact device identities or authorized stream addresses. Saving a network address/password requires explicit Keychain selection.'))
        button=QPushButton('Manage cameras / discover CCTV…');button.clicked.connect(self.cameras_requested.emit);page.addWidget(button)
        self.camera_table=QTableWidget(0,5);self.camera_table.setHorizontalHeaderLabels(['Name','Connection','Last frame (UTC)','Authentication','AI'])
        self.camera_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.camera_table.horizontalHeader().setStretchLastSection(True);page.addWidget(self.camera_table)
    def _incidents(self):
        page=self._page('Incident center')
        row=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Search incident ID, camera or category')
        self.status_filter=QComboBox();self.status_filter.addItems(['All statuses',*TRANSITIONS])
        self.category_filter=QComboBox();self.category_filter.addItems(['All categories','weapon_handgun','weapon_firearm','weapon_longgun','weapon_knife','fire','smoke'])
        refresh=QPushButton('Refresh');refresh.clicked.connect(self.refresh)
        row.addWidget(self.search,1);row.addWidget(self.category_filter);row.addWidget(self.status_filter);row.addWidget(refresh);page.addLayout(row)
        date_row=QHBoxLayout();self.date_filter=QCheckBox('Filter UTC time range');date_row.addWidget(self.date_filter)
        self.start_time=QDateTimeEdit(QDateTime.currentDateTimeUtc().addDays(-7));self.end_time=QDateTimeEdit(QDateTime.currentDateTimeUtc().addDays(1))
        for field in (self.start_time,self.end_time):field.setTimeZone(QTimeZone.utc());field.setDisplayFormat('yyyy-MM-dd HH:mm');field.setCalendarPopup(True);date_row.addWidget(field)
        page.addLayout(date_row)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['First observed (UTC)','Possible category','Confidence','Severity','Status','Camera ID','Incident ID'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selection_changed);page.addWidget(self.table)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(115);page.addWidget(self.details)
        self.note=QLineEdit();self.note.setPlaceholderText('Human review note (saved in audit when recording is enabled)');page.addWidget(self.note)
        actions=QHBoxLayout();self.review_buttons={}
        for title,status in [('Acknowledge','ACKNOWLEDGED'),('Verify','VERIFIED'),('Dismiss','DISMISSED'),('Close','CLOSED')]:
            button=QPushButton(title);button.setEnabled(False);button.clicked.connect(lambda checked=False,s=status:self.review(s));actions.addWidget(button);self.review_buttons[status]=button
        for title,action in [('Audit trail',self.audit),('View saved evidence',self.preview),('Delete incident / evidence',self.delete)]:
            button=QPushButton(title);button.clicked.connect(action);actions.addWidget(button)
        page.addLayout(actions)
        page.addWidget(caption('Unrecorded incidents are session-only. Verify means an operator reviewed the visual evidence; it does not establish criminal intent. Delete removes local files, without guaranteeing physical erasure on an SSD.'))
    def refresh(self):
        filters={'search':self.search.text().strip()}
        if self.status_filter.currentIndex():filters['status']=self.status_filter.currentText()
        if self.category_filter.currentIndex():filters['category']=self.category_filter.currentText()
        if self.date_filter.isChecked():
            filters['start']=self.start_time.dateTime().toUTC().toString(Qt.DateFormat.ISODateWithMs)
            filters['end']=self.end_time.dateTime().toUTC().toString(Qt.DateFormat.ISODateWithMs)
        self.service.refresh(filters)
    def selected(self):
        index=self.table.currentRow();return self.rows[index] if 0<=index<len(self.rows) else None
    def _selection_changed(self):
        row=self.selected();allowed=TRANSITIONS.get(row['status'],()) if row else ()
        for status,button in self.review_buttons.items():button.setEnabled(status in allowed)
        self.details.setPlainText((f"Possible {row['category'].replace('weapon_','').replace('_',' ')} · confidence {row['confidence']:.1%} · severity {row['severity']}/4\nModel: {row['model_id']} · version {row['model_version']}\nFirst observed: {row['first_seen']} · last: {row['last_seen']}\nStatus: {row['status']} · track {row.get('track_id','unassigned')} · box {row['bbox']}") if row else 'Select an incident to review.')
    def show_records(self,rows):
        selected=self.selected();ident=selected['incident_id'] if selected else None
        self.rows=list(rows);self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,key in enumerate(('first_seen','category','confidence','severity','status','source_id','incident_id')):
                value=f"{row[key]:.1%}" if key=='confidence' else str(row.get(key,''))
                self.table.setItem(i,j,QTableWidgetItem(value))
            if row['incident_id']==ident:self.table.selectRow(i)
        self.table.resizeColumnsToContents();self._selection_changed()
    def incident_changed(self,row):
        if self.isVisible():self.refresh()
    def review(self,status):
        row=self.selected()
        if row:self.service.review(row['incident_id'],status,self.note.text().strip())
    def audit(self):
        row=self.selected()
        if row:self.service.audit(row['incident_id'])
    def preview(self):
        row=self.selected()
        if row:self.service.preview(row['incident_id'])
    def delete(self):
        row=self.selected()
        if row and QMessageBox.question(self,'Delete local incident','Delete this incident and its saved evidence? The deletion audit entry remains.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.service.delete(row['incident_id'])
    def show_audit(self,entries):
        dialog=QDialog(self);dialog.setWindowTitle('Local review audit');dialog.resize(700,480)
        layout=QVBoxLayout(dialog);text=QPlainTextEdit(json.dumps(entries,indent=2,default=str));text.setReadOnly(True);layout.addWidget(text);dialog.exec()
    def show_evidence(self,path):
        dialog=QDialog(self);dialog.setWindowTitle('Authorized local evidence · integrity checked');dialog.resize(820,620)
        layout=QVBoxLayout(dialog);view=QLabel();view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        view.setPixmap(QPixmap(path).scaled(790,560,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation));layout.addWidget(view);dialog.exec()
    def _settings(self):
        page=self._page('AI settings');scroll=QScrollArea();scroll.setWidgetResizable(True);inner=QWidget();form=QFormLayout(inner);scroll.setWidget(inner);page.addWidget(scroll)
        self.detector_checks={}
        for key,title in [('weapons','Possible weapons'),('fire_smoke','Fire / smoke model'),('ghs','GHS pictograms (experimental, optional)')]:
            check=QCheckBox(title);check.setChecked(key in self.settings.detectors)
            if key=='ghs':
                check.setChecked(False);check.setEnabled(False)
                check.setText('GHS pictograms (unavailable in this build)')
                check.setToolTip('No independently validated local pictogram detector is installed.')
            self.detector_checks[key]=check;form.addRow(check)
        self.fire_check=QCheckBox('Visible flame observations');self.fire_check.setChecked(self.settings.detect_fire);form.addRow(self.fire_check)
        self.smoke_check=QCheckBox('Visible smoke observations');self.smoke_check.setChecked(self.settings.detect_smoke);form.addRow(self.smoke_check)
        self.fields={}
        parameters=[('display_confidence','Hazard box display score',.05,.99,.05),('confidence','Alert confidence threshold',.05,.99,.05),('min_consecutive','Consecutive analyzed samples',2,100,1),('persistence_s','Minimum persistence (media seconds)',0,60,.1),('max_gap_s','Maximum missed-observation gap (seconds)',.05,10,.05),('cooldown_s','Category / camera alert cooldown (seconds)',1,3600,1),('sample_interval_s','Analyze hazards at most every (seconds)',.05,10,.05),('retention_days','Saved incident retention (days)',1,365,1),('max_incidents','Saved / session incident limit',100,100000,100),('audio_volume','Optional sound volume',0,1,.1),('audio_severity','Sound minimum severity (1–4)',1,4,1)]
        integers={'min_consecutive','retention_days','max_incidents','audio_severity'}
        for key,title,minimum,maximum,step in parameters:
            field=QSpinBox() if key in integers else QDoubleSpinBox()
            field.setRange(minimum,maximum);field.setSingleStep(step);field.setValue(getattr(self.settings,key));self.fields[key]=field;form.addRow(title,field)
        self.category_override=QCheckBox('Use per-category box display thresholds')
        self.category_override.setChecked(bool(self.settings.category_thresholds));form.addRow(self.category_override)
        self.category_fields={}
        for category in ('weapon_handgun','weapon_longgun','weapon_firearm','weapon_knife','fire','smoke'):
            field=QDoubleSpinBox();field.setRange(.05,.99);field.setSingleStep(.05)
            field.setValue(self.settings.category_thresholds.get(category,self.settings.display_confidence))
            self.category_fields[category]=field;form.addRow(category.replace('weapon_','Possible ').replace('_',' ')+' boxes',field)
        form.addRow(caption('Boxes show model observations immediately, including objects without a tracking ID. Alerts separately require confidence and temporal confirmation. Lower scores can increase false positives.'))
        form.addRow(caption('Resolution is controlled in the live sidebar. Newest-frame and incident-sample queues each retain one frame; older samples are dropped to keep latency bounded.'))
        self.camera_override=QCheckBox('Apply confidence / temporal values only to the current source');form.addRow(self.camera_override)
        clear=QPushButton('Remove current source override');clear.clicked.connect(self.clear_camera_override);form.addRow(clear)
        self.settings_message=caption('Preferences do not enable monitoring, evidence recording, sound or desktop notifications.');form.addRow(self.settings_message)
        save=QPushButton('Save and apply settings');save.clicked.connect(self.apply_settings);page.addWidget(save)
    def clear_camera_override(self):
        rules=dict(self.settings.camera_rules);rules.pop(self.current_source,None)
        try:
            candidate=replace(self.settings,camera_rules=rules);candidate.save()
            self.settings=candidate;self.settings_applied.emit(candidate)
            self.settings_message.setText('Current source override removed.')
        except (ValueError,OSError):self.settings_message.setText('The camera override could not be saved.')
    def apply_settings(self):
        try:
            values={key:field.value() for key,field in self.fields.items()}
            values['category_thresholds']={key:field.value() for key,field in self.category_fields.items()} if self.category_override.isChecked() else {}
            values.update(detectors=tuple(key for key,check in self.detector_checks.items() if check.isChecked()),detect_fire=self.fire_check.isChecked(),detect_smoke=self.smoke_check.isChecked())
            if self.camera_override.isChecked():
                if not self.current_source:raise ValueError('Start a source before saving a camera-specific rule.')
                rules=dict(self.settings.camera_rules)
                keys=('confidence','min_consecutive','persistence_s','max_gap_s','cooldown_s')
                rule={('confidence_threshold' if key=='confidence' else key):values.pop(key) for key in keys}
                rules[self.current_source]=rule;values['camera_rules']=rules
            candidate=replace(self.settings,**values)
            candidate.save();self.settings=candidate;self.settings_applied.emit(candidate)
            self.settings_message.setText('Saved. Temporal candidates reset when rules change; existing human review remains.')
        except (ValueError,TypeError,OSError) as exc:self.settings_message.setText(f'Settings were not saved: {exc}')
    def _diagnostics(self):
        page=self._page('Diagnostics');self.diagnostics=QPlainTextEdit();self.diagnostics.setReadOnly(True);page.addWidget(self.diagnostics)
        page.addWidget(caption('Timings and memory are measured locally. CPU percent may exceed 100% across multiple cores. GPU utilization is unavailable. Alert persistence uses source media time; it is not emergency-response latency. Detector load failures remain visible.'))
    def update_runtime(self,state,source,packet=None,cameras=()):
        active=state=='running';paused=state=='paused'
        self.summary.setText(f"{'Monitoring' if active else 'Paused' if paused else 'Inactive'} · {source or 'No selected source'} · {state}")
        if packet is not None:
            self.current_source=getattr(self.parent(),'_active_source_id','')
            if active:self.ai_health.setPlainText(json.dumps(packet.detector_health or {'hazards':'disabled or not sampled'},indent=2,default=str))
            diagnostic={**packet.diagnostics,'source_state':state,'frame_index':packet.frame_index,'frame_timestamp_utc':packet.timestamp,'media_time_s':packet.source_time_s,'processing_fps':packet.fps,'inference_ms':packet.inference_ms,'frame_age_ms':packet.frame_age_ms,'captured_frames_skipped':packet.dropped_frames,'incident_samples_skipped':self.service.dropped_samples,'base_model':packet.model_name,'base_device':packet.device,'detector_health':packet.detector_health}
            diagnostic['sample_source']=source
            self._last_diagnostic=diagnostic
        diagnostic=dict(self._last_diagnostic)
        diagnostic.update(source_state=state,monitoring_active=active)
        diagnostic['measurement_status']=('Latest received timestamped sample' if active else 'Historical last sample; no active inference') if self._last_diagnostic else 'No measurement received'
        self.diagnostics.setPlainText(json.dumps(diagnostic,indent=2,default=str))
        if not active:self.ai_health.setPlainText('No active inference. Start a selected video or camera to measure model health.')
        elif packet is None:self.ai_health.setPlainText('Waiting for a fresh inference sample. Previous measured values remain in Diagnostics.')
        self.camera_table.setRowCount(len(cameras))
        for i,camera in enumerate(cameras):
            for j,value in enumerate((camera.name,camera.connection_health,camera.last_frame_utc or 'No frame yet',camera.authentication_status,camera.ai_status)):
                self.camera_table.setItem(i,j,QTableWidgetItem(str(value)))
        self.camera_table.resizeColumnsToContents()
    def showEvent(self,event):
        super().showEvent(event);self.refresh()
