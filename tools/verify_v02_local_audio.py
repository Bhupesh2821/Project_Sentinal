"""Native Qt output-state check; no microphone and no assertion of human hearing."""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaDevices,QSoundEffect
from sentinal.interface.local_alerts import LocalAlertOutput
from sentinal.storage.incident_database import utc_now
from sentinal.config import ROOT

app=QApplication([]);output=LocalAlertOutput();states=[];deliveries=[]
output.sound.playingChanged.connect(lambda:states.append({'elapsed_s':round(time.monotonic()-started,4),'playing':output.sound.isPlaying()}))
output.delivery.connect(deliveries.append)
started=time.monotonic();deadline=started+8
while output.sound.status() not in (QSoundEffect.Status.Ready,QSoundEffect.Status.Error) and time.monotonic()<deadline:
    app.processEvents();time.sleep(.005)
ready=output.sound.status()==QSoundEffect.Status.Ready
output.configure(audio=True,desktop=False,volume=.15,severity=3)
if ready:
    output.send({'status':'ALERTED','incident_id':'verification-local-audio','severity':3,'category':'fire','last_seen':utc_now()})
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
        if any(s['playing'] for s in states) and not output.sound.isPlaying():break
report={'timestamp':utc_now(),'test':'Actual local Qt sound-output state; no microphone/audio recording','ready':ready,'status':str(output.sound.status()),'audio_devices':[device.description() for device in QMediaDevices.audioOutputs()],'selected_device':output.sound.audioDevice().description(),'volume':output.sound.volume(),'playing_transitions':states,'delivery_requests':deliveries,'pass':ready and any(s['playing'] for s in states) and not output.sound.isPlaying(),'limitation':'Output transitions do not prove that a person heard sound; visual alerts remain primary.'}
output.close();app.processEvents()
path=ROOT/'docs/evidence/v02-2026-10-30/local-audio.json';path.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
raise SystemExit(0 if report['pass'] else 1)
