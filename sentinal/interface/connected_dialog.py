"""Explicit authenticated metadata delivery; camera capture stays independent."""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QCheckBox,QPushButton,QLabel,QFileDialog,QHBoxLayout
from sentinal.config import ROOT
from sentinal.connected.edge import EdgeConfig


class ConnectedDialog(QDialog):
    def __init__(self,bridge,parent=None):
        super().__init__(parent);self.bridge=bridge
        self.setWindowTitle('SENTINAL · Connected command center');self.resize(610,455)
        layout=QVBoxLayout(self)
        info=QLabel('Enable outbound alert metadata and device health only for your authorized command center. Video, evidence, camera addresses and passwords are not part of this connection. Camera monitoring still requires Start.');info.setWordWrap(True);layout.addWidget(info)
        form=QFormLayout();layout.addLayout(form)
        self.url=QLineEdit();self.url.setPlaceholderText('https://your-authorized-service');form.addRow('Backend origin',self.url)
        self.device=QLineEdit();self.device.setPlaceholderText('Provisioned edge device ID');form.addRow('Edge device ID',self.device)
        self.secret=QLineEdit();self.secret.setEchoMode(QLineEdit.EchoMode.Password);form.addRow('Provisioned device secret',self.secret)
        self.local=QCheckBox('Allow HTTP only for a local loopback development service');form.addRow(self.local)
        self.ca_file=None
        self.tunables={}
        buttons=QHBoxLayout();load=QPushButton('Load paired device file…');load.clicked.connect(self.load_config);buttons.addWidget(load)
        save=QPushButton('Save credentials locally');save.clicked.connect(self.save_config);buttons.addWidget(save);layout.addLayout(buttons)
        self.enabled=QCheckBox('Enable outbound incident metadata');self.enabled.setChecked(bridge.is_enabled);self.enabled.toggled.connect(self.toggle);layout.addWidget(self.enabled)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.message=QLabel('Off by default. Local pending metadata remains private and bounded; each destination uses its own outbox.');self.message.setWordWrap(True);layout.addWidget(self.message)
        close=QPushButton('Close settings');close.clicked.connect(self.close);layout.addWidget(close)
        bridge.status_changed.connect(self.show_status);bridge.error.connect(self.message.setText)
        self.show_status(bridge.status())
    def config(self):
        return EdgeConfig(self.url.text().strip(),self.device.text().strip(),self.secret.text(),self.local.isChecked(),self.ca_file,**self.tunables)
    def load_config(self):
        name,_=QFileDialog.getOpenFileName(self,'Select an owner-only paired device file',str(ROOT/'config/connected'),'JSON settings (*.json)')
        if not name:return
        try:
            config=EdgeConfig.load(name);self.url.setText(config.server_url);self.device.setText(config.device_id);self.secret.setText(config.secret);self.local.setChecked(config.allow_loopback_http);self.ca_file=config.ca_file
            self.tunables={key:getattr(config,key) for key in ('request_timeout_s','max_attempts','ingest_path')}
            self.message.setText('Loaded locally. Enable outbound metadata explicitly when ready.')
        except Exception:self.message.setText('Credentials could not be loaded. Choose an owner-only file inside this project with valid device settings.')
    def save_config(self):
        try:self.config().save();self.message.setText('Saved in the project’s owner-only connected settings. Delivery is not enabled by saving.')
        except Exception:self.message.setText('Settings were not saved. Check the backend origin, device ID, secret and local development option.')
    def toggle(self,enabled):
        if not enabled:self.bridge.stop();return
        try:self.bridge.start(self.config());self.message.setText('Outbound metadata explicitly enabled. Check actual delivery status below.')
        except Exception:
            with QSignalBlocker(self.enabled):self.enabled.setChecked(False)
            self.message.setText('Delivery could not start. Check the paired device settings and wait for an earlier connection to stop.')
    def show_status(self,value):
        state=value.get('state','disabled')
        self.status.setText(f"Connection: {state} · pending {value.get('queued',0)} · delivered {value.get('delivered',0)} · failed {value.get('failed',0)}")
        if state in {'disabled','stopped','error'}:
            with QSignalBlocker(self.enabled):self.enabled.setChecked(False)
