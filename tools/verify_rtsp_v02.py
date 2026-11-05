#!/usr/bin/env python3
"""Actual loopback-only H264 RTSP inference, interruption and recovery.

Uses project-local optional MediaMTX/FFmpeg verification tools. No camera is
activated, no outgoing network access, no mocked inference, no footage saved.
The input is the previously documented public moving-video fixture.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def stop_process(process):
    if process is None:return
    if process.poll() is None:
        process.terminate()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)


class LocalRTSP:
    def __init__(self, directory, video=None, username='', password=''):
        self.directory=Path(directory)
        self.video=Path(video or ROOT/'tests/fixtures/vtest.avi')
        self.tool_dir=ROOT/'work/v02-network-tools'
        self.server=self.publisher=None
        self._handles=[]
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));self.port=listener.getsockname()[1]
        self.username,self.password=username,password
        self.endpoint=f'rtsp://127.0.0.1:{self.port}/sentinal-fixture'
        self.url=(f"rtsp://{quote(username,safe='')}:{quote(password,safe='')}@127.0.0.1:{self.port}/sentinal-fixture" if username else self.endpoint)
    def start(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        config=self.directory/'mediamtx-local.yml'
        user=json.dumps(self.username) if self.username else 'any'
        password=('  pass: '+json.dumps(self.password)+'\n') if self.username else ''
        config.write_text(f'''logLevel: warn
logDestinations: [stdout]
rtsp: true
rtspAddress: 127.0.0.1:{self.port}
rtspTransports: [tcp]
rtmp: false
hls: false
webrtc: false
srt: false
moq: false
api: false
metrics: false
pprof: false
playback: false
authMethod: internal
authInternalUsers:
- user: {user}
{password}  ips: [127.0.0.1]
  permissions:
  - action: publish
    path: sentinal-fixture
  - action: read
    path: sentinal-fixture
paths:
  sentinal-fixture:
    source: publisher
''')
        config.chmod(0o600)
        handle=(self.directory/'mediamtx.log').open('w');self._handles.append(handle)
        self.server=subprocess.Popen([str(self.tool_dir/'mediamtx/mediamtx'),str(config)],cwd=ROOT,stdout=handle,stderr=handle)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if self.server.poll() is not None:raise RuntimeError('Loopback RTSP server did not start; see local verification log')
            try:
                with socket.create_connection(('127.0.0.1',self.port),timeout=.1):break
            except OSError:time.sleep(.05)
        else:raise RuntimeError('Loopback RTSP listener did not become ready')
        self.start_publisher();return self
    def start_publisher(self):
        if self.publisher is not None and self.publisher.poll() is None:return
        handle=(self.directory/'publisher.log').open('a');self._handles.append(handle)
        self.publisher=subprocess.Popen([str(self.tool_dir/'ffmpeg'),'-hide_banner','-loglevel','warning','-nostdin',
            '-re','-stream_loop','-1','-i',str(self.video),'-an','-vf','scale=640:480','-c:v','libx264',
            '-preset','ultrafast','-tune','zerolatency','-pix_fmt','yuv420p','-g','10','-r','10',
            '-f','rtsp','-rtsp_transport','tcp',self.url],cwd=ROOT,stdout=handle,stderr=handle)
        time.sleep(.5)
        if self.publisher.poll() is not None:raise RuntimeError('Recorded-fixture RTSP publisher did not start')
    def interrupt(self):stop_process(self.publisher)
    def close(self):
        stop_process(self.publisher);stop_process(self.server)
        for handle in self._handles:handle.close()
        self._handles=[]


def main():
    from PySide6.QtCore import QCoreApplication
    from sentinal.config import AppConfig
    from sentinal.storage.camera_registry import CameraRegistry
    from sentinal.vision.inference_worker import InferenceWorker
    app=QCoreApplication([])
    evidence=ROOT/'docs/evidence/v02-2026-10-30'
    evidence.mkdir(parents=True,exist_ok=True)
    report={'test':'Actual loopback H264 RTSP through existing live capture and real YOLO/ByteTrack',
        'created_utc':datetime.now(timezone.utc).isoformat(),'physical_cctv_tested':False,
        'camera_activated':False,'mock_inference':False,'footage_saved':False,
        'transport':'RTSP/TCP loopback only','fixture':'tests/fixtures/vtest.avi',
        'checks':{},'states':[],'frames':[],'errors':[]}
    worker=feed=registry=None
    started=time.monotonic()
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    def pump_until(predicate,timeout=25):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            app.processEvents()
            packet=worker.take_latest() if worker else None
            if packet is not None:
                report['frames'].append({'session_id':packet.session_id,'frame_index':packet.frame_index,
                    'source_time_s':packet.source_time_s,'fps':packet.fps,'inference_ms':packet.inference_ms,
                    'device':packet.device,'frame_age_ms':packet.frame_age_ms,'dropped_frames':packet.dropped_frames,
                    'labels':[d.label for d in packet.detections],
                    'ids':[d.track_id for d in packet.detections if d.track_id is not None],
                    'elapsed_s':time.monotonic()-started})
            if predicate():return
            time.sleep(.005)
        raise AssertionError('Timed out waiting for actual RTSP state or frames')
    try:
        with tempfile.TemporaryDirectory(prefix='rtsp-v02-',dir=ROOT/'work/tmp') as temp:
            feed=LocalRTSP(temp).start()
            registry=CameraRegistry(Path(temp)/'cameras.sqlite3')
            record=registry.upsert_network('Authorized loopback H264 fixture',feed.url)
            selection=registry.resolve(record.camera_id)
            check('registry_explicit_stream_resolution',selection.spec.kind=='stream')
            worker=InferenceWorker(AppConfig(device='auto',image_size=480,stream_open_timeout_ms=4000,
                stream_read_timeout_ms=2000,stream_reconnect_attempts=5,stream_reconnect_delay_s=.2))
            worker.state_changed.connect(lambda state,message:report['states'].append({'state':state,'elapsed_s':time.monotonic()-started}))
            worker.error.connect(lambda message:report['errors'].append(message))
            worker.start();worker.request_start(selection.spec)
            pump_until(lambda:len(report['frames'])>=15)
            check('actual_rtsp_frames_decoded',len(report['frames'])>=15)
            check('real_person_detection',any('person' in frame['labels'] for frame in report['frames']))
            check('real_bytetrack_ids',any(frame['ids'] for frame in report['frames']))
            first_session=report['frames'][-1]['session_id']
            check('initial_session_stable',len({f['session_id'] for f in report['frames']})==1)
            state_offset=len(report['states'])
            feed.interrupt()
            pump_until(lambda:any(s['state']=='reconnecting' for s in report['states'][state_offset:]),15)
            check('disconnect_reported_reconnecting',True)
            feed.start_publisher()
            pump_until(lambda:any(f['session_id']!=first_session for f in report['frames']),25)
            check('recovery_creates_fresh_tracking_session',True)
            recovery_session=report['frames'][-1]['session_id']
            recovery_offset=len(report['frames'])
            target=len(report['frames'])+10
            pump_until(lambda:len(report['frames'])>=target)
            check('recovered_session_stable',all(f['session_id']==recovery_session for f in report['frames'][recovery_offset:]))
            worker.request_stop()
            pump_until(lambda:any(s['state']=='stopped' for s in report['states']),8)
            check('stop_releases_live_capture',worker.pipeline.source is None)
            worker.request_shutdown();worker.wait(8000)
            check('worker_shutdown',not worker.isRunning())
            check('no_worker_errors',not report['errors'])
            registry.close();registry=None
            feed.close()
            check('server_and_publisher_stopped',feed.server.poll() is not None and feed.publisher.poll() is not None)
    except Exception as exc:report['failure']=str(exc)
    finally:
        if worker is not None and worker.isRunning():worker.request_shutdown();worker.wait(8000)
        if registry is not None:registry.close()
        if feed is not None:feed.close()
        report['elapsed_s']=time.monotonic()-started
        report['passed']=bool(report['checks']) and all(report['checks'].values()) and 'failure' not in report
        (evidence/'rtsp-loopback.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({key:report[key] for key in ['passed','checks','errors','elapsed_s']},indent=2))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
