#!/usr/bin/env python3
"""Verify dynamic user-video import/playback and actual network-video input.

Network verification is a real loopback HTTP MJPEG connection carrying public
recorded footage. It is not physical IP-camera or private-user-footage proof.
No webcam or microphone is activated. All generated files remain in this project.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def file_info(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'filename': path.name, 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


class RecordedMJPEGFeed:
    """An actual authenticated HTTP server serving real recorded moving frames."""
    def __init__(self, video, fps=10):
        self.video, self.fps = str(video), fps
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.generation = self.connections = self.challenges = self.frames = self.active = self.drops = 0
        self.errors = []
        self.username = 'sentinal-local-verification'
        self.password = 'local-verification-only-password'
        self.token = 'local-verification-only-query'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_):
                pass

            def empty_response(self, status):
                self.send_response(status)
                self.send_header('Content-Length', '0')
                self.send_header('Connection', 'close')
                if status == 401:
                    self.send_header('WWW-Authenticate', 'Basic realm="SENTINAL local verification"')
                self.end_headers()
                self.close_connection = True

            def do_GET(self):
                if self.path.split('?', 1)[0] != '/moving-recorded-feed':
                    self.empty_response(404)
                    return
                expected = 'Basic ' + base64.b64encode(f'{owner.username}:{owner.password}'.encode()).decode()
                if self.headers.get('Authorization') != expected:
                    with owner.lock:
                        owner.challenges += 1
                    self.empty_response(401)
                    return
                import cv2
                with owner.lock:
                    owner.connections += 1
                    owner.active += 1
                    generation = owner.generation
                capture = cv2.VideoCapture(owner.video)
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=sentinalframe')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    while not owner.stop.is_set():
                        started = time.monotonic()
                        with owner.lock:
                            drop = generation != owner.generation
                        if drop:
                            with owner.lock:
                                owner.drops += 1
                            try:
                                self.connection.shutdown(socket.SHUT_RDWR)
                            except OSError:
                                pass
                            self.close_connection = True
                            return
                        ok, frame = capture.read()
                        if not ok:
                            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ok, frame = capture.read()
                        if not ok:
                            raise RuntimeError('Real recorded network fixture failed to decode')
                        ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        if not ok:
                            raise RuntimeError('Real recorded frame failed to JPEG-encode')
                        payload = jpeg.tobytes()
                        self.wfile.write(b'--sentinalframe\r\nContent-Type: image/jpeg\r\nContent-Length: '
                                         + str(len(payload)).encode() + b'\r\n\r\n' + payload + b'\r\n')
                        self.wfile.flush()
                        with owner.lock:
                            owner.frames += 1
                        owner.stop.wait(max(0, 1 / owner.fps - (time.monotonic() - started)))
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                except Exception as exc:
                    with owner.lock:
                        owner.errors.append(type(exc).__name__)
                finally:
                    capture.release()
                    with owner.lock:
                        owner.active -= 1

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True,
                                       name='SENTINAL verification HTTP feed')

    @property
    def port(self):
        return self.server.server_address[1]

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}/moving-recorded-feed?token={self.token}'

    def start(self):
        self.thread.start()
        return self

    def disconnect(self):
        with self.lock:
            self.generation += 1

    def close(self):
        self.stop.set()
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        deadline = time.monotonic() + 3
        while self.active and time.monotonic() < deadline:
            time.sleep(.02)

    def summary(self):
        with self.lock:
            return {'transport': 'Actual HTTP multipart MJPEG, loopback only', 'physical_ip_camera': False,
                    'input': 'Real recorded moving footage', 'authorized_connections': self.connections,
                    'auth_challenges': self.challenges, 'frames_sent': self.frames,
                    'controlled_disconnects': self.drops, 'handlers_remaining': self.active,
                    'server_thread_stopped': not self.thread.is_alive(), 'errors': list(self.errors)}


def make_second_video(source, directory):
    import cv2
    for filename, codec in [('Uploaded real footage second clip.mp4', 'mp4v'),
                            ('Uploaded real footage second clip.avi', 'MJPG')]:
        cap = cv2.VideoCapture(str(source))
        cap.set(cv2.CAP_PROP_POS_FRAMES, 100)
        ok, frame = cap.read()
        if not ok:
            cap.release()
            raise RuntimeError('Cannot decode real footage for the second import')
        path = Path(directory) / filename
        height, width = frame.shape[:2]
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), 10, (width, height))
        written = 0
        try:
            if writer.isOpened():
                while ok and written < 70:
                    writer.write(frame)
                    written += 1
                    ok, frame = cap.read()
        finally:
            writer.release()
            cap.release()
        probe = cv2.VideoCapture(str(path))
        try:
            decoded, image = probe.read()
        finally:
            probe.release()
        if decoded and image is not None and written >= 20:
            return path, {**file_info(path), 'derived_real_source_frames': [100, 100 + written - 1],
                          'frames_written': written, 'synthetic_motion': False, 'avi_fallback': codec == 'MJPG'}
        path.unlink(missing_ok=True)
    raise RuntimeError('Neither MP4V nor MJPG created a decodable second real-video input')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, default=ROOT / 'tests/fixtures/vtest.avi')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/evidence/real-inputs-2026-10-27')
    parser.add_argument('--device', choices=('auto', 'cpu', 'mps'), default='auto')
    parser.add_argument('--offscreen', action='store_true')
    args = parser.parse_args()
    if args.offscreen:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from sentinal.config import AppConfig
    from sentinal.application import prepare_runtime
    from sentinal.core.logger import configure_logging
    import cv2
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLineEdit
    from sentinal.interface.main_window import MainWindow
    from sentinal.interface.themes import STYLESHEET

    video, output = args.video.expanduser().resolve(), args.output.expanduser().resolve()
    if not video.is_file():
        parser.error('Supply an existing real recorded-video fixture')
    if not output.is_relative_to(ROOT):
        parser.error('Verification output must remain in this project')
    output.mkdir(parents=True, exist_ok=True)
    configure_logging()
    log_path = ROOT / 'logs/sentinal.log'
    log_offset = log_path.stat().st_size if log_path.exists() else 0
    report = {'test': 'Dynamic user-video workflow and actual loopback network input, with real inference',
              'created_utc': datetime.now(timezone.utc).isoformat(),
              'display_mode': 'offscreen' if args.offscreen else 'native',
              'camera_activated': False, 'mock_inference': False,
              'external_physical_ip_camera_tested': False, 'private_user_video_tested': False,
              'fixture': file_info(video), 'checks': {}, 'frames': [], 'states': [], 'failures': []}
    print('Preparing actual video-import, playback and network-feed verification…', flush=True)
    report['runtime_preparation'] = prepare_runtime()
    app = QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLESHEET)
    report['qt_platform'] = app.platformName()
    window = MainWindow(AppConfig(device=args.device, stream_open_timeout_ms=5000,
                                stream_read_timeout_ms=1500, stream_reconnect_attempts=3,
                                stream_reconnect_delay_s=.2))
    stage, heartbeat, seen = ['startup'], [], set()
    started = time.monotonic()
    window.worker.state_changed.connect(lambda state, _: report['states'].append(
        {'stage': stage[0], 'state': state, 'elapsed_s': round(time.monotonic() - started, 3)}))
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeat.append((stage[0], time.monotonic())))
    timer.start()
    window.show()
    feed = temporary = None

    def check(name, condition, detail=None):
        report['checks'][name] = {'passed': bool(condition), 'detail': detail}
        if not condition:
            raise AssertionError(name)

    def observe():
        p = window.last_packet
        if p is None or (p.session_id, p.frame_index) in seen:
            return
        seen.add((p.session_id, p.frame_index))
        report['frames'].append({'stage': stage[0], 'session_id': p.session_id,
            'frame_index': p.frame_index, 'source_time_s': p.source_time_s, 'source': p.source,
            'device': p.device, 'processing_fps': p.fps, 'vision_ms': p.inference_ms,
            'frame_age_ms': getattr(p, 'frame_age_ms', 0), 'dropped_frames': getattr(p, 'dropped_frames', 0),
            'labels': [d.label for d in p.detections],
            'track_ids': [d.track_id for d in p.detections if d.track_id is not None]})

    def pump(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            observe()
            time.sleep(.005)

    def wait_for(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            observe()
            if predicate():
                return
            time.sleep(.005)
        raise AssertionError(f'Timed out in {stage[0]}, state={window._state}: {window.error_banner.text()}')

    def save_image(name):
        app.processEvents()
        window._poll_frame()
        check('saved_' + name, window.grab().save(str(output / name)))

    def database_hash():
        path = ROOT / 'recordings/detections.sqlite3'
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

    database_before = database_hash()
    try:
        wait_for(lambda: len(heartbeat) > 10, 5)
        check('window_visible', window.isVisible())
        check('no_camera_or_pipeline_at_startup', window.worker.pipeline is None)
        check('metadata_disabled_at_startup', not window.metadata_toggle.isChecked())
        check('drag_drop_available', window.acceptDrops())
        stage[0] = 'first_dynamic_import'
        print('Importing an actual local recorded video through the GUI import worker…', flush=True)
        window.begin_video_import(str(video))
        wait_for(lambda: window._import_worker is None and window.last_packet is not None
                 and window.last_packet.frame_index >= 8, 180)
        first_session = window.last_packet.session_id
        pipeline_id, model_id = id(window.worker.pipeline), id(window.worker.pipeline.detector.model)
        imported = Path(window.video_path).resolve()
        check('import_inside_project', imported.is_relative_to(ROOT / 'data/videos'))
        check('imported_bytes_match_original', file_info(imported)['sha256'] == report['fixture']['sha256'])
        check('original_video_unchanged', file_info(video) == report['fixture'])
        check('real_imported_video_detections', any(f['labels'] for f in report['frames']))
        check('real_imported_video_tracking_ids', any(f['track_ids'] for f in report['frames']))
        check('new_import_enabled_during_monitoring', window.open_button.isEnabled())
        check('seek_enabled_for_video', window.seek_slider.isEnabled())
        check('pause_enabled_for_video', window.pause_button.isEnabled())
        report['first_managed_video'] = {'path': str(imported.relative_to(ROOT)), **file_info(imported)}
        save_image('dynamic-uploaded-video.png')

        stage[0] = 'pause_seek_resume'
        window.pause_button.click()
        wait_for(lambda: window._state == 'paused')
        pump(.2)
        paused_index = window.last_packet.frame_index
        pump(.6)
        check('pause_stops_processing_frames', window.last_packet.frame_index == paused_index)
        check('pause_keeps_file_open', window.worker.pipeline.source is not None)
        duration = float(window._playback.get('duration_s') or 0)
        check('video_duration_measured', duration > 2)
        target = min(duration * .4, 20)
        window.seek_slider.setValue(round(target / duration * 1000))
        window._seek_released()
        wait_for(lambda: window.last_packet is not None and window.last_packet.session_id != first_session, 90)
        check('seek_creates_new_tracking_session', window.last_packet.session_id != first_session)
        check('seek_preserves_paused_state', window._state == 'paused')
        check('seek_reads_requested_media_position', abs(window.last_packet.source_time_s - target) < 1,
              {'requested_s': target, 'observed_s': window.last_packet.source_time_s})
        before_resume = window.last_packet.frame_index
        window.pause_button.click()
        wait_for(lambda: window._state == 'running' and window.last_packet.frame_index >= before_resume + 3, 45)
        check('resume_advances_video', window.last_packet.frame_index > before_resume)

        stage[0] = 'prepare_second_recorded_input'
        temporary = tempfile.TemporaryDirectory(prefix='sentinal-real-inputs-', dir=ROOT / 'work/tmp')
        second, second_info = make_second_video(video, temporary.name)
        report['second_input'] = second_info
        check('second_input_has_different_real_video_bytes', second_info['sha256'] != report['fixture']['sha256'])
        stage[0] = 'dynamic_replacement_while_running'
        print('Importing a different recorded video while the application is monitoring…', flush=True)
        old_session = window.last_packet.session_id
        window.begin_video_import(str(second))
        wait_for(lambda: window._import_worker is None and window.last_packet is not None
                 and window.last_packet.session_id != old_session and Path(window.video_path).name != imported.name
                 and window.last_packet.frame_index >= 3, 120)
        check('second_import_switches_without_restart', window._state in {'running', 'eof'})
        check('second_import_reuses_model', id(window.worker.pipeline) == pipeline_id
              and id(window.worker.pipeline.detector.model) == model_id)
        check('second_import_is_project_local', Path(window.video_path).resolve().is_relative_to(ROOT / 'data/videos'))
        check('library_lists_both_imports', window.library_combo.count() >= 3)
        save_image('dynamic-second-video.png')
        window.stop_button.click()
        wait_for(lambda: window._state in {'stopped', 'eof'})
        check('file_stop_releases_source', window.worker.pipeline.source is None)

        stage[0] = 'actual_loopback_network_feed'
        print('Reading an authenticated HTTP MJPEG feed through FFmpeg and the actual model…', flush=True)
        feed = RecordedMJPEGFeed(video).start()
        window.source_type.setCurrentIndex(2)
        window.stream_url.setText(feed.url)
        window.stream_username.setText(feed.username)
        window.stream_password.setText(feed.password)
        check('password_widget_masks_input', window.stream_password.echoMode() == QLineEdit.EchoMode.Password)
        window.start_button.click()
        wait_for(lambda: window._state == 'running' and window.last_packet is not None
                 and window._current_spec.kind == 'stream' and window.last_packet.frame_index >= 8, 120)
        network_session = window.last_packet.session_id
        previous_live = window.worker.pipeline.source
        check('network_video_has_actual_detections', any(f['labels'] and f['stage'] == stage[0] for f in report['frames']))
        check('network_video_has_tracking_ids', any(f['track_ids'] and f['stage'] == stage[0] for f in report['frames']))
        check('live_frame_age_measured', window.last_packet.frame_age_ms >= 0)
        check('live_skipped_frames_measured', window.last_packet.dropped_frames >= 0)
        check('live_source_cannot_seek', not window.seek_slider.isEnabled())
        sensitive = [feed.username, feed.password, feed.token]
        check('network_source_label_redacted', all(s not in window.last_packet.source
              and s not in window.source_name.text() for s in sensitive))
        check('network_transport_is_loopback_only', '127.0.0.1' in window.last_packet.source)
        save_image('actual-network-feed.png')

        stage[0] = 'network_dropout_reconnect'
        print('Interrupting the real connection to test bounded recovery and track reset…', flush=True)
        feed.disconnect()
        wait_for(lambda: any(s['state'] == 'reconnecting' for s in report['states'])
                 and window.last_packet is not None and window.last_packet.session_id != network_session
                 and window._state == 'running', 60)
        check('real_disconnect_triggered_reconnection', feed.drops >= 1)
        check('reconnect_has_fresh_tracking_session', window.last_packet.session_id != network_session)
        check('previous_live_process_and_buffer_closed', previous_live.capture is None and previous_live._memory is None)
        latest_live = window.worker.pipeline.source
        stage[0] = 'network_stop'
        stop_started = time.monotonic()
        window.stop_button.click()
        wait_for(lambda: window._state == 'stopped', 12)
        stop_s = time.monotonic() - stop_started
        report['network_stop_s'] = stop_s
        check('network_stop_completes_within_bound', stop_s < 8, stop_s)
        check('network_stop_releases_process_and_shared_memory', latest_live.capture is None and latest_live._memory is None)
        check('network_stop_releases_pipeline_source', window.worker.pipeline.source is None)

        stage[0] = 'unavailable_network_endpoint'
        window.stream_url.setText(f'http://127.0.0.1:{feed.port}/unavailable?token={feed.token}')
        window.start_button.click()
        wait_for(lambda: window._state == 'error', 15)
        check('network_error_readable', bool(window.error_banner.text()))
        check('network_error_releases_source', window.worker.pipeline.source is None)
        check('network_error_redacts_secrets', all(s not in window.error_banner.text() for s in sensitive))
        check('network_error_allows_retry', window.start_button.isEnabled())
        check('metadata_stays_disabled', not window.metadata_toggle.isChecked())
        check('detection_database_unchanged', database_hash() == database_before)
        check('ui_heartbeat_active', len(heartbeat) > 50)
        tail = log_path.read_text(errors='replace')[log_offset:] if log_path.exists() else ''
        check('diagnostic_log_has_no_test_credentials', all(s not in tail for s in sensitive))
    except Exception as exc:
        report['failures'].append(str(exc))
        report['technical_error'] = traceback.format_exc()
        try:
            save_image('real-inputs-failure.png')
        except Exception:
            pass
    finally:
        stage[0] = 'shutdown'
        window.close()
        try:
            wait_for(lambda: not window.worker.isRunning() and window._import_worker is None, 30)
            report['checks']['workers_shutdown'] = {'passed': True}
        except Exception as exc:
            report['checks']['workers_shutdown'] = {'passed': False}
            report['failures'].append(f'Shutdown: {exc}')
        if feed is not None:
            feed.close()
            report['network_fixture'] = feed.summary()
            report['checks']['network_server_shutdown'] = {'passed': not feed.thread.is_alive() and not feed.active}
        if temporary is not None:
            temporary.cleanup()
        timer.stop()
        per_stage = {}
        for name in sorted({p[0] for p in heartbeat}):
            gaps = [(b[1] - a[1]) * 1000 for a, b in zip(heartbeat, heartbeat[1:]) if a[0] == b[0] == name]
            per_stage[name] = {'callbacks': sum(p[0] == name for p in heartbeat),
                'maximum_gap_ms': max(gaps) if gaps else None,
                'p95_gap_ms': sorted(gaps)[int(.95 * (len(gaps) - 1))] if gaps else None}
        report['ui_heartbeat'] = {'callbacks': len(heartbeat), 'interval_ms': 10, 'per_stage': per_stage,
            'note': 'Synchronous second-clip creation is verifier preparation, not production import work.'}
        report['elapsed_s'] = time.monotonic() - started
        report['limits'] = ['Actual HTTP connection carries recorded public footage; no physical IP camera was tested.',
                            'Dynamic workflow supports user-selected files, but no private user video was available for this run.',
                            'Numerical track continuity is not ground-truth person identity or long-occlusion accuracy.',
                            'No camera or audio was captured by this verifier.']
        report['passed'] = not report['failures'] and all(c['passed'] for c in report['checks'].values())
        destination = output / 'real-inputs-verification.json'
        destination.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']),
                          'failures': report['failures'], 'evidence': str(destination)}, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
