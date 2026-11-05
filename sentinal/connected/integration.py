"""Optional Qt adapter; ordinary desktop monitoring stays local by default."""
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from .edge import EdgeConfig, EdgePublisher


class DesktopEdgeBridge(QObject):
    """UI-safe metadata delivery, activated only by an explicit user action.

    Credentials can be loaded separately, but attaching a service, importing this
    module, or constructing this object never creates an outbox or sends data.
    Stop does not block the UI; close() belongs in orderly application shutdown.
    """
    status_changed = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None, path=None):
        super().__init__(parent)
        self.path = path
        self.publisher = None
        self._service = None
        self._provider = None
        self._enabled = False
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(10000)
        self._heartbeat.timeout.connect(self._send_heartbeat)
        self._poll = QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._check_stopped)

    @property
    def is_running(self):
        return self.publisher is not None and self.publisher.is_alive()

    @property
    def is_enabled(self):
        return self._enabled and self.is_running

    def set_health_provider(self, provider=None):
        if provider is not None and not callable(provider):
            raise ValueError('Health provider must be callable')
        self._provider = provider

    def attach(self, service):
        if self._service is service:
            return
        if self._service is not None:
            try:
                self._service.incident_changed.disconnect(self.publish_incident)
            except (RuntimeError, TypeError):
                pass
        self._service = service
        service.incident_changed.connect(self.publish_incident)

    def start(self, config):
        if self.is_running:
            raise ValueError('Wait for the previous metadata connection to stop')
        if not isinstance(config, EdgeConfig):
            raise ValueError('Configure device credentials before enabling outbound metadata')
        self.publisher = EdgePublisher(config, path=self.path, on_status=self.status_changed.emit)
        self._enabled = True
        self.publisher.start()
        self._heartbeat.start()
        self._poll.start()
        self._send_heartbeat()

    @Slot(object)
    def publish_incident(self, row):
        if not self.is_enabled:
            return
        try:
            self.publisher.submit_incident(row)
        except (ValueError, TypeError, KeyError):
            self.error.emit('Incident metadata was not queued. Check connected diagnostics; local monitoring continues.')

    def _send_heartbeat(self):
        if not self.is_enabled:
            return
        try:
            values = self._provider() if self._provider is not None else {'health': {'status': 'idle'}}
            if not isinstance(values, dict) or set(values) - {'health', 'cameras', 'models'}:
                raise ValueError('Invalid health provider output')
            self.publisher.submit_heartbeat(values.get('health', {'status': 'idle'}),
                values.get('cameras', ()), values.get('models', ()))
        except Exception:
            self.error.emit('Device health was not queued. Local monitoring continues.')

    def _check_stopped(self):
        if self.publisher is not None and not self.publisher.is_alive():
            self._enabled = False
            self._heartbeat.stop()
            self._poll.stop()
            self.status_changed.emit(self.publisher.status())

    def status(self):
        return self.publisher.status() if self.publisher is not None else {'state': 'disabled', 'queued': 0, 'failed': 0, 'delivered': 0}

    def stop(self):
        self._enabled = False
        self._heartbeat.stop()
        if self.publisher is not None:
            self.publisher.request_stop()
            self.status_changed.emit({**self.publisher.status(), 'state': 'stopping'})

    def close(self, timeout=5):
        self.stop()
        if self.publisher is None:
            return True
        released = self.publisher.close(timeout)
        if released:
            self._poll.stop()
        return released
