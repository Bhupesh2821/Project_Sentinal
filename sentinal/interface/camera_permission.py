"""GUI-owned camera consent, requested only by an explicit camera action."""
from PySide6.QtCore import QObject,Signal,QCameraPermission,QThread,Qt
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

DENIED_MESSAGE=('Camera access was not granted. In macOS System Settings → Privacy & Security → Camera, '
                'allow SENTINAL, then reopen it and press Start. No camera was opened. '
                'If a system policy restricts access, contact the device administrator.')


class QtCameraPermissionBackend:
    def _app(self):
        app=QApplication.instance()
        if app is None or QThread.currentThread()!=app.thread():
            raise RuntimeError('Camera consent requires the application GUI thread')
        return app
    def check(self):return self._app().checkPermission(QCameraPermission())
    def request(self,context,callback):self._app().requestPermission(QCameraPermission(),context,callback)


class CameraPermissionGate(QObject):
    """One native request; cancelling invalidates intent without changing OS consent."""
    pending_changed=Signal(bool)
    error=Signal(str)
    def __init__(self,parent=None,backend=None):
        super().__init__(parent);self._backend=backend or QtCameraPermissionBackend()
        self._generation=0;self._inflight=False;self._continuation=None;self._owner=None
    @property
    def pending(self):return self._continuation is not None
    def pending_for(self,owner):return self.pending and self._owner is owner
    def cancel(self,owner=None):
        if owner is not None and self._owner is not owner:return
        was_pending=self.pending;self._generation+=1;self._continuation=None;self._owner=None
        if was_pending:self.pending_changed.emit(False)
    def _continue(self,callback):
        try:callback();return True
        except Exception:
            self.error.emit('Camera permission was checked, but monitoring could not start safely. Check the current source status and use Stop before retrying.')
            return False
    def ensure(self,owner,on_granted):
        if self._inflight:
            self.error.emit('A camera permission dialog is already pending. Finish it, then press Start again. No additional camera was opened.')
            return False
        self._generation+=1
        try:status=self._backend.check()
        except Exception:
            self.error.emit('Camera permission could not be checked from the application window. Reopen SENTINAL and try again; no camera was opened.')
            return False
        if status==Qt.PermissionStatus.Granted:
            return self._continue(on_granted)
        if status!=Qt.PermissionStatus.Undetermined:
            self.error.emit(DENIED_MESSAGE);return False
        self._generation+=1;generation=self._generation
        self._owner=owner;self._continuation=on_granted;self._inflight=True
        self.pending_changed.emit(True)
        def finished(permission):
            if not isValid(self):return
            self._inflight=False
            if generation!=self._generation or self._continuation is None:return
            continuation=self._continuation;self._continuation=None
            self.pending_changed.emit(False)
            if generation!=self._generation:return
            self._owner=None
            try:granted=permission.status()==Qt.PermissionStatus.Granted
            except Exception:granted=False
            if granted:self._continue(continuation)
            else:self.error.emit(DENIED_MESSAGE)
        try:self._backend.request(self,finished)
        except Exception:
            self._inflight=False;self.cancel()
            self.error.emit('The macOS camera permission prompt could not open. Reopen the native SENTINAL app and try again; no camera was opened.')
        return False
