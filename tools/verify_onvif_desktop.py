#!/usr/bin/env python3
"""Native ONVIF setup -> selected HTTP video -> actual local YOLO/ByteTrack.

The device is a controlled loopback SOAP server. Its feed carries the public
OpenCV vtest recording, not a physical CCTV or private camera. No inference,
ONVIF, Qt worker or decoder is mocked. No webcam or microphone is opened.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from verify_real_inputs import RecordedMJPEGFeed, file_info


class RecordedOnvifDevice:
    """A read-only test device advertising a real, authenticated HTTP feed."""
    def __init__(self, feed):
        self.feed = feed
        self.actions = []
        self.auth_challenges = 0
        self.wsse_valid = []
        self.errors = []
        self.active = 0
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_):
                pass

            def reply(self, code, payload=b''):
                self.send_response(code)
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Content-Type', 'application/soap+xml; charset=utf-8')
                self.send_header('Connection', 'close')
                if code == 401:
                    self.send_header('WWW-Authenticate', 'Basic realm="SENTINAL ONVIF verification"')
                self.end_headers()
                self.close_connection = True
                if payload:
                    self.wfile.write(payload)

            def do_POST(self):
                with owner.lock:
                    owner.active += 1
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 65536:
                        self.reply(400)
                        return
                    request = self.rfile.read(length)
                    expected = 'Basic ' + base64.b64encode(f'{owner.feed.username}:{owner.feed.password}'.encode()).decode()
                    if self.headers.get('Authorization') != expected:
                        with owner.lock:
                            owner.auth_challenges += 1
                        self.reply(401)
                        return
                    root = ET.fromstring(request)
                    def nodes(name):
                        return [node for node in root.iter() if node.tag.rsplit('}', 1)[-1] == name]
                    operation = list(nodes('Body')[0])[0].tag.rsplit('}', 1)[-1]
                    nonce, created, digest = [nodes(name)[0].text for name in ('Nonce', 'Created', 'Password')]
                    expected_digest = base64.b64encode(hashlib.sha1(base64.b64decode(nonce) + created.encode() + owner.feed.password.encode()).digest()).decode()
                    valid = digest == expected_digest and owner.feed.password.encode() not in request
                    with owner.lock:
                        owner.actions.append(operation)
                        owner.wsse_valid.append(valid)
                    endpoint = f'http://127.0.0.1:{self.server.server_port}/onvif/media'
                    if operation == 'GetCapabilities':
                        body = f'<GetCapabilitiesResponse><Media><XAddr>{endpoint}</XAddr></Media></GetCapabilitiesResponse>'
                    elif operation == 'GetProfiles':
                        body = '<t:GetProfilesResponse><t:Profiles token="recorded-main"><tt:Name>Public recorded verification</tt:Name><tt:VideoEncoderConfiguration><tt:Encoding>JPEG</tt:Encoding><tt:Resolution><tt:Width>768</tt:Width><tt:Height>576</tt:Height></tt:Resolution></tt:VideoEncoderConfiguration></t:Profiles></t:GetProfilesResponse>'
                    elif operation == 'GetStreamUri':
                        body = f'<t:GetStreamUriResponse><t:MediaUri><tt:Uri>{owner.feed.url}</tt:Uri></t:MediaUri></t:GetStreamUriResponse>'
                    else:
                        self.reply(400)
                        return
                    payload = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
                               'xmlns:t="http://www.onvif.org/ver10/media/wsdl" '
                               'xmlns:tt="http://www.onvif.org/ver10/schema"><s:Body>' + body +
                               '</s:Body></s:Envelope>').encode()
                    self.reply(200, payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as exc:
                    with owner.lock:
                        owner.errors.append(type(exc).__name__)
                finally:
                    with owner.lock:
                        owner.active -= 1

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True,
                                       name='SENTINAL verification ONVIF device')

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}/onvif/device_service'

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def summary(self):
        with self.lock:
            return {'transport': 'Actual loopback HTTP SOAP', 'physical_cctv': False,
                    'actions': list(self.actions), 'auth_challenges': self.auth_challenges,
                    'wsse_password_digests_valid': all(self.wsse_valid) and bool(self.wsse_valid),
                    'handlers_remaining': self.active, 'errors': list(self.errors),
                    'server_thread_stopped': not self.thread.is_alive()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, default=ROOT / 'tests/fixtures/vtest.avi')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/evidence/camera-cctv-catalog-2026-10-28/onvif-desktop.json')
    parser.add_argument('--device', choices=('auto', 'cpu', 'mps'), default='auto')
    parser.add_argument('--offscreen', action='store_true')
    args = parser.parse_args()
    if args.offscreen:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    video, output = args.video.expanduser().resolve(), args.output.expanduser().resolve()
    if not video.is_file() or not video.is_relative_to(ROOT):
        parser.error('Use a real recorded fixture inside Project Sentinal')
    if not output.is_relative_to(ROOT):
        parser.error('Evidence must remain in Project Sentinal')
    output.parent.mkdir(parents=True, exist_ok=True)
    from sentinal.application import prepare_runtime
    from sentinal.config import AppConfig
    from sentinal.core.logger import configure_logging
    from sentinal.interface.main_window import MainWindow
    from sentinal.interface.themes import STYLESHEET
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLineEdit
    configure_logging()
    report = {'test': 'Actual ONVIF dialog-to-video desktop integration',
              'created_utc': datetime.now(timezone.utc).isoformat(),
              'mock_inference': False, 'mock_onvif': False, 'mock_transport': False,
              'physical_cctv_tested': False, 'camera_activated': False, 'microphone_opened': False,
              'fixture': file_info(video), 'checks': {}, 'frames': [], 'states': [], 'failures': []}
    print('Preparing native ONVIF setup and real recorded-video inference…', flush=True)
    report['runtime_preparation'] = prepare_runtime()
    app = QApplication([])
    app.setStyle('Fusion'); app.setStyleSheet(STYLESHEET)
    report['qt_platform'] = app.platformName()
    window = MainWindow(AppConfig(device=args.device))
    window.show()
    started = time.monotonic()
    heartbeat = []
    timer = QTimer(); timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeat.append(time.monotonic())); timer.start()
    seen = set()
    window.worker.state_changed.connect(lambda state, _: report['states'].append(state))
    feed = RecordedMJPEGFeed(video).start()
    device = RecordedOnvifDevice(feed).start()
    log_path = ROOT / 'logs/sentinal.log'
    log_before = log_path.read_text(errors='replace') if log_path.exists() else ''
    def databases():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (ROOT / 'recordings').glob('detections.sqlite3*') if p.is_file()}
    database_before = databases()
    def check(name, condition, detail=None):
        report['checks'][name] = {'passed': bool(condition), 'detail': detail}
        if not condition:
            raise AssertionError(name)
    def observe():
        packet = window.last_packet
        if packet is not None and (packet.session_id, packet.frame_index) not in seen:
            seen.add((packet.session_id, packet.frame_index))
            report['frames'].append({'session_id': packet.session_id, 'frame_index': packet.frame_index,
                'device': packet.device, 'model_name': packet.model_name, 'source': packet.source,
                'fps': packet.fps, 'vision_ms': packet.inference_ms, 'frame_age_ms': packet.frame_age_ms,
                'labels': [d.label for d in packet.detections],
                'track_ids': [d.track_id for d in packet.detections if d.track_id is not None]})
    def wait(predicate, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents(); observe()
            if predicate():
                return
            time.sleep(.005)
        raise AssertionError('Desktop integration timed out; state=' + window._state)
    try:
        wait(lambda: len(heartbeat) >= 10, 5)
        check('native_window_visible', window.isVisible())
        check('standby_has_no_pipeline', window.worker.pipeline is None)
        check('metadata_disabled_initially', not window.metadata_toggle.isChecked())
        window.source_type.setCurrentIndex(2)
        window.network_setup_button.click()
        dialog = window._network_dialog
        check('actual_network_setup_dialog_visible', dialog is not None and dialog.isVisible())
        check('opening_dialog_does_not_connect_video', feed.connections == 0 and feed.frames == 0)
        dialog.address.setText(device.url)
        dialog.username.setText(feed.username); dialog.password.setText(feed.password)
        check('setup_password_masked', dialog.password.echoMode() == QLineEdit.EchoMode.Password)
        dialog.profiles_button.click()
        wait(lambda: not dialog.setup_running and dialog.use_button.isEnabled(), 15)
        check('actual_soap_operations_completed', device.actions == ['GetCapabilities', 'GetProfiles', 'GetStreamUri'])
        check('actual_http_authentication_challenged', device.auth_challenges == 3)
        check('wsse_password_digest_verified', all(device.wsse_valid) and len(device.wsse_valid) == 3)
        check('lookup_does_not_connect_video', feed.connections == 0 and feed.frames == 0)
        check('returned_profile_visible', dialog.profile_combo.count() == 1 and 'Public recorded' in dialog.profile_combo.currentText())
        dialog.use_button.click(); app.processEvents()
        check('use_stream_populates_main_window', window.stream_url.text() == feed.url and window.source_type.currentIndex() == 2)
        check('use_stream_does_not_auto_start', not window._busy and window.worker.pipeline is None and feed.connections == 0)
        check('main_password_masked', window.stream_password.echoMode() == QLineEdit.EchoMode.Password)
        check('closed_setup_drops_password', dialog.password.text() == '' and not dialog._streams)
        window.start_button.click()
        wait(lambda: window._state == 'running' and len(report['frames']) >= 8
             and any('person' in f['labels'] for f in report['frames'])
             and any(f['track_ids'] for f in report['frames']), 90)
        check('real_recorded_network_frames_received', feed.connections >= 1 and feed.frames >= 8)
        check('actual_person_detections', any('person' in f['labels'] for f in report['frames']))
        check('actual_tracking_ids', any(f['track_ids'] for f in report['frames']))
        check('selected_source_is_network', window._current_spec.kind == 'stream')
        check('source_labels_redact_credentials_and_query', all(secret not in window.last_packet.source + window.source_name.text()
              for secret in (feed.username, feed.password, feed.token)))
        check('measured_performance_available', all(f['vision_ms'] > 0 and f['fps'] > 0 for f in report['frames']))
        check('live_playback_controls_disabled', not window.seek_slider.isEnabled() and not window.pause_button.isEnabled())
        check('public_video_panel_screenshot_saved', window.video_panel.grab().save(str(output.with_name('onvif-public-video.png'))))
        live = window.worker.pipeline.source
        stop_started = time.monotonic()
        window.stop_button.click(); wait(lambda: window._state == 'stopped', 12)
        report['stop_s'] = time.monotonic() - stop_started
        check('stop_is_bounded', report['stop_s'] < 8, report['stop_s'])
        check('stop_releases_capture_and_memory', live.capture is None and live._memory is None)
        check('stop_releases_pipeline_source', window.worker.pipeline.source is None)
        check('metadata_stays_disabled', not window.metadata_toggle.isChecked())
        check('user_detection_database_unchanged', databases() == database_before)
        check('ui_heartbeat_continues', len(heartbeat) > 40)
        log_after = log_path.read_text(errors='replace') if log_path.exists() else ''
        tail = log_after[len(log_before):] if log_after.startswith(log_before) else log_after
        check('diagnostic_log_has_no_test_secrets', all(secret not in tail for secret in (feed.username, feed.password, feed.token)))
    except Exception as exc:
        report['failures'].append(type(exc).__name__ + ': ' + str(exc))
        report['technical_error'] = traceback.format_exc()
    finally:
        window.close()
        try:
            wait(lambda: not window.worker.isRunning() and not (window._network_dialog and window._network_dialog.setup_running), 30)
            report['checks']['worker_and_setup_shutdown'] = {'passed': True}
        except Exception as exc:
            report['checks']['worker_and_setup_shutdown'] = {'passed': False}
            report['failures'].append('Shutdown: ' + str(exc))
        device.close(); feed.close(); timer.stop()
        report['onvif_device'] = device.summary()
        report['recorded_network_feed'] = feed.summary()
        report['checks']['test_servers_shutdown'] = {'passed': not device.thread.is_alive() and not feed.thread.is_alive()
            and device.active == 0 and feed.active == 0 and not device.errors and not feed.errors}
        report['checks']['final_detection_database_unchanged'] = {'passed': databases() == database_before}
        report['elapsed_s'] = time.monotonic() - started
        report['ui_heartbeat_callbacks'] = len(heartbeat)
        report['limits'] = ['A controlled loopback ONVIF device advertised real recorded-video HTTP MJPEG; no physical CCTV was tested.',
            'No actual LAN multicast discovery, RTSP hardware, private video, webcam or microphone was used.',
            'Person/track observations demonstrate execution, not calibrated accuracy or ground-truth identity.']
        report['passed'] = not report['failures'] and all(item['passed'] for item in report['checks'].values())
        output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'failures': report['failures'],
                          'evidence': str(output)}, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
