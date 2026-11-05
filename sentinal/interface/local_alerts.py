"""Opt-in local audio/desktop alerts. No external recipients or microphone."""
from pathlib import Path
import time
import math
from PySide6.QtCore import QObject,Signal,QUrl
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QSystemTrayIcon,QApplication,QStyle

class LocalAlertOutput(QObject):
    delivery=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.audio_enabled=False;self.desktop_enabled=False;self.severity=3
        self._seen=set();self._last_sound=0.0
        self.sound=QSoundEffect(self);self.sound.setLoopCount(1);self.sound.setVolume(.5)
        self.sound.setSource(QUrl.fromLocalFile(str(Path(__file__).parent/'assets/alert.wav')))
        self.tray=QSystemTrayIcon(self)
        self.tray.setIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))
    def configure(self,audio=False,desktop=False,volume=.5,severity=3):
        if type(audio) is not bool or type(desktop) is not bool:raise ValueError('Alert controls require explicit booleans')
        if type(volume) not in (int,float) or not math.isfinite(volume) or not 0<=volume<=1:raise ValueError('Volume must be zero to one')
        if type(severity) is not int or not 1<=severity<=4:raise ValueError('Audio severity must be one to four')
        self.audio_enabled=audio;self.desktop_enabled=desktop;self.severity=severity
        self.sound.setVolume(float(volume))
        if not self.audio_enabled:self.sound.stop()
        self.tray.setVisible(self.desktop_enabled and QSystemTrayIcon.isSystemTrayAvailable())
    def test_sound(self):
        if self.sound.status()!=QSoundEffect.Status.Ready:return False
        self.sound.play();return True
    def send(self,incident):
        if incident['status']!='ALERTED' or incident['incident_id'] in self._seen:return
        self._seen.add(incident['incident_id'])
        if len(self._seen)>2048:self._seen={incident['incident_id']}
        ident=incident['incident_id'];now=time.monotonic()
        if self.audio_enabled and incident['severity']>=self.severity:
            if now-self._last_sound>=10 and not self.sound.isPlaying():
                success=self.test_sound()
                if success:self._last_sound=now
                self.delivery.emit({'incident_id':ident,'channel':'local_audio','status':'submitted' if success else 'unavailable'})
        if self.desktop_enabled:
            available=QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages()
            if available:self.tray.showMessage('SENTINAL · Possible '+incident['category'].replace('_',' '),'Awaiting human verification · '+incident['last_seen'],QSystemTrayIcon.MessageIcon.Warning,8000)
            self.delivery.emit({'incident_id':ident,'channel':'desktop','status':'submitted' if available else 'unavailable'})
    def close(self):self.sound.stop();self.tray.hide()
