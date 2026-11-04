#!/usr/bin/env python3
"""Actual disposable local RTSP authentication; never uses real credentials."""
from datetime import datetime,timezone
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from verify_rtsp_v02 import LocalRTSP

def main():
    from sentinal.storage.camera_registry import CameraRegistry
    from sentinal.vision.live_capture import LiveVideoSource
    from sentinal.vision.video_source import SourceSpec,VideoSourceError
    report={'test':'Actual loopback H264 RTSP authentication with disposable local credentials',
        'created_utc':datetime.now(timezone.utc).isoformat(),'physical_cctv_tested':False,
        'camera_activated':False,'secret_values_recorded':False,'checks':{}}
    started=time.monotonic()
    def check(name,condition):
        report['checks'][name]=bool(condition)
        if not condition:raise AssertionError(name)
    try:
        with tempfile.TemporaryDirectory(prefix='rtsp-auth-v02-',dir=ROOT/'work/tmp') as temp:
            password=secrets.token_hex(20)
            feed=LocalRTSP(temp,username='sentinal-disposable-test',password=password).start()
            registry=source=None
            try:
                source=LiveVideoSource(SourceSpec('stream',feed.endpoint.replace('rtsp://','rtsp://invalid:invalid@')),open_timeout_ms=2000,read_timeout_ms=1000)
                rejected=False
                try:source.open()
                except VideoSourceError as exc:
                    rejected=True
                    check('failure_does_not_echo_secret',password not in str(exc))
                finally:source.close()
                check('invalid_credentials_rejected',rejected)
                check('failed_open_resources_released',source.capture is None)
                registry=CameraRegistry(Path(temp)/'private/registry.sqlite3')
                record=registry.upsert_network('Disposable authorized RTSP fixture',feed.endpoint,feed.username,feed.password)
                selection=registry.resolve(record.camera_id)
                check('sqlite_contains_no_credentials',password.encode() not in registry.path.read_bytes())
                source=LiveVideoSource(selection.spec,open_timeout_ms=4000,read_timeout_ms=2000)
                source.open();frame=source.read()
                check('valid_credentials_receive_actual_frame',frame is not None and frame.shape==(480,640,3))
                del frame
                source.close();check('successful_source_released',source.capture is None)
            finally:
                if source is not None:source.close()
                if registry is not None:registry.close()
                feed.close()
                check('server_and_publisher_stopped',feed.server.poll() is not None and feed.publisher.poll() is not None)
    except Exception as exc:report['failure']=str(exc)
    report['elapsed_s']=time.monotonic()-started
    report['passed']=bool(report['checks']) and all(report['checks'].values()) and 'failure' not in report
    (ROOT/'docs/evidence/v02-2026-10-30/rtsp-authentication.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
