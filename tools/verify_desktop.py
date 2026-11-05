#!/usr/bin/env python3
"""Exercise the actual desktop worker with real footage and save evidence.

Run from the project environment:
    python tools/verify_desktop.py --video /path/to/real-footage.avi
No camera is activated by this verifier. Its short EOF fixture is a real
12-frame extract from the supplied footage, never synthetic detections.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", default=str(ROOT / "docs/verification"))
    parser.add_argument("--device", choices=("auto", "cpu", "mps"), default="auto")
    parser.add_argument("--offscreen", action="store_true", help="Render without native display; evidence is labeled accordingly")
    args = parser.parse_args()
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    library_start = time.monotonic()
    print("Loading local video and desktop libraries…", flush=True)
    import cv2
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from sentinal.config import AppConfig
    from sentinal.application import prepare_runtime
    from sentinal.core.logger import configure_logging
    from sentinal.interface.main_window import MainWindow
    from sentinal.interface.themes import STYLESHEET
    configure_logging()
    print("Preparing local vision libraries before showing the interface…", flush=True)
    prepared_runtime = prepare_runtime()
    print(f"Libraries loaded; opening the monitoring interface ({'offscreen' if args.offscreen else 'native'})…", flush=True)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    from sentinal.core.event_manager import EventManager as ActualEventManager
    from sentinal.vision import inference_worker as worker_module
    user_database = ROOT / "recordings/detections.sqlite3"
    user_database_before = hashlib.sha256(user_database.read_bytes()).hexdigest() if user_database.exists() else None
    metadata_database = output / "verification-metadata.sqlite3"
    original_event_manager = worker_module.EventManager
    # Only redirect storage. The real EventManager, SQLite and vision stay active.
    worker_module.EventManager = lambda config: ActualEventManager(config, path=metadata_database)
    video = Path(args.video).resolve()
    if not video.is_file():
        raise SystemExit(f"Real video fixture does not exist: {video}")

    evidence = {
        "test": "actual Qt desktop and real YOLO/ByteTrack video pipeline",
        "mock_inference": False,
        "camera_access_attempted": False,
        "display_mode": "offscreen" if args.offscreen else "native",
        "requested_device": args.device,
        "checks": {},
        "frames": [],
        "failures": [],
        "runtime_preparation": prepared_runtime,
        "metadata_database": str(metadata_database),
        "metadata_isolated_from_user_store": True,
    }
    verification_started = time.monotonic()
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    evidence["qt_platform"] = app.platformName()
    window = MainWindow(AppConfig(device=args.device))
    evidence["startup_before_window_s"] = time.monotonic() - library_start
    window.show()
    stage = ["startup"]
    heartbeats = []
    seen_frames = set()
    heartbeat = QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: heartbeats.append((stage[0], time.monotonic())))
    heartbeat.start()

    def observe():
        current = window.last_packet
        if current is None or (current.session_id, current.frame_index) in seen_frames:
            return
        seen_frames.add((current.session_id, current.frame_index))
        evidence["frames"].append({
            "stage": stage[0], "session_id": current.session_id,
            "observed_elapsed_s": round(time.monotonic() - verification_started, 3),
            "frame_index": current.frame_index, "device": current.device,
            "fps": current.fps, "vision_ms": current.inference_ms,
            "average_vision_ms": current.average_inference_ms,
            "labels": [d.label for d in current.detections],
            "track_ids": [d.track_id for d in current.detections if d.track_id is not None],
        })

    def wait_for(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            observe()
            if predicate():
                return
            time.sleep(.005)
        raise AssertionError(f"Timed out during {stage[0]}: {window._state}; {window.error_banner.text()}")

    def check(name, condition, detail=None):
        evidence["checks"][name] = {"passed": bool(condition), "detail": detail}
        if not condition:
            raise AssertionError(name)

    def save_image(name):
        app.processEvents()
        window._poll_frame()
        saved = window.grab().save(str(output / name))
        check(f"saved_{name}", saved)

    def metadata_rows(session):
        path = metadata_database
        if not path.exists():
            return 0
        try:
            with sqlite3.connect(str(path), timeout=.2) as connection:
                return connection.execute("SELECT COUNT(*) FROM detections WHERE session_id=?", (session,)).fetchone()[0]
        except sqlite3.Error:
            return 0

    try:
        wait_for(lambda: len(heartbeats) > 10, 5)
        check("desktop_rendered", window.isVisible())
        check("startup_camera_inactive", window.worker.pipeline is None)
        check("metadata_disabled_at_startup", not window.metadata_toggle.isChecked())
        save_image("desktop-standby.png")
        window.load_video(str(video))
        stage[0] = "first_real_video"
        print("Testing actual pretrained inference and tracking on local video…", flush=True)
        window.start_button.click()
        wait_for(lambda: window.last_packet is not None and window.last_packet.frame_index >= 8, 180)
        session_one = window.last_packet.session_id
        check("real_video_frames_displayed", window.last_packet.frame.shape[0] > 0)
        check("real_detections", any(frame["labels"] for frame in evidence["frames"]))
        check("real_tracking_ids", any(frame["track_ids"] for frame in evidence["frames"]))
        check("measured_fps_and_latency", window.last_packet.fps > 0 and window.last_packet.average_inference_ms > 0)
        stage[0] = "controls_and_metadata"
        window.confidence_slider.setValue(30)
        window.filter_combo.setCurrentIndex(1)
        check("confidence_control", window.confidence_label.text() == "30%")
        for toggle, attr in ((window.boxes_toggle, "show_boxes"), (window.labels_toggle, "show_labels"), (window.ids_toggle, "show_ids")):
            toggle.setChecked(False)
            check(f"toggle_{attr}_off", not getattr(window.video_panel, attr))
            toggle.setChecked(True)
            check(f"toggle_{attr}_on", getattr(window.video_panel, attr))
        previous_frame = window.last_packet.frame_index
        wait_for(lambda: window.last_packet.frame_index >= previous_frame + 2 and all(d.label in {"person", "backpack", "handbag", "suitcase"} for d in window.last_packet.detections), 60)
        check("focus_filter_applied_to_actual_packet", all(d.label in {"person", "backpack", "handbag", "suitcase"} for d in window.last_packet.detections))
        window.metadata_toggle.setChecked(True)
        wait_for(lambda: metadata_rows(session_one) > 0, 30)
        check("optional_metadata_persisted", metadata_rows(session_one) > 0)
        window.metadata_toggle.setChecked(False)
        save_image("desktop-monitoring.png")
        stage[0] = "first_stop"
        print("Checking safe stop, restart, source switch, end-of-file and recovery…", flush=True)
        window.stop_button.click()
        wait_for(lambda: window._state == "stopped")
        check("stop_released_source", window.worker.pipeline.source is None)
        check("stop_restored_controls", window.start_button.isEnabled() and not window.stop_button.isEnabled())

        stage[0] = "restart_real_video"
        pipeline_identity = id(window.worker.pipeline)
        window.start_button.click()
        wait_for(lambda: window.last_packet is not None and window.last_packet.frame_index >= 4, 90)
        check("restart_new_session", window.last_packet.session_id != session_one)
        check("restart_reused_model_pipeline", id(window.worker.pipeline) == pipeline_identity)
        window.stop_button.click()
        wait_for(lambda: window._state == "stopped")

        with tempfile.TemporaryDirectory(prefix="sentinal-real-clip-") as temporary:
            stage[0] = "verifier_clip_extraction"
            extraction_started = time.monotonic()
            clip = Path(temporary) / "real-footage-short.avi"
            capture = cv2.VideoCapture(str(video))
            ok, frame = capture.read()
            if not ok:
                raise AssertionError("Cannot extract short clip from real footage")
            writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"MJPG"), 8, (frame.shape[1], frame.shape[0]))
            if not writer.isOpened():
                capture.release()
                raise AssertionError("OpenCV cannot create the real-footage EOF fixture")
            frames_written = 0
            try:
                while ok and frames_written < 12:
                    writer.write(frame)
                    frames_written += 1
                    ok, frame = capture.read()
            finally:
                writer.release()
                capture.release()
            check("real_short_clip_created", frames_written == 12)
            evidence["verifier_clip_extraction_ms"] = (time.monotonic() - extraction_started) * 1000
            stage[0] = "source_switch_and_eof"
            window.load_video(str(clip))
            window.start_button.click()
            wait_for(lambda: window._state == "eof", 90)
            check("source_switch_opened_other_video", "real-footage-short.avi" in window.last_packet.source)
            check("eof_releases_source", window.worker.pipeline.source is None)
            check("eof_replay_control", window.start_button.text() == "Replay video")
            eof_session = window.last_packet.session_id
            stage[0] = "replay"
            window.start_button.click()
            wait_for(lambda: window.last_packet is not None and window.last_packet.session_id != eof_session, 90)
            window.stop_button.click()
            wait_for(lambda: window._state == "stopped" or window._state == "eof")
            check("replay_uses_new_session", window.last_packet.session_id != eof_session)
            stage[0] = "missing_video"
            window.load_video(str(Path(temporary) / "does-not-exist.mp4"))
            window.start_button.click()
            wait_for(lambda: window._state == "error", 30)
            check("missing_file_understandable_error", bool(window.error_banner.text()))
            check("failure_releases_source", window.worker.pipeline.source is None)
            check("failure_allows_retry", window.start_button.isEnabled())
            save_image("desktop-source-error.png")
            stage[0] = "error_recovery"
            window.load_video(str(clip))
            window.start_button.click()
            wait_for(lambda: window.last_packet is not None, 90)
            check("recovered_after_missing_file", window._state in ("running", "eof"))
            window.stop_button.click()
            wait_for(lambda: window._state in ("stopped", "eof"))
        check("ui_heartbeat_active", len(heartbeats) > 20)
    except Exception as exc:
        evidence["failures"].append(str(exc))
        evidence["technical_error"] = traceback.format_exc()
        try:
            save_image("desktop-failure.png")
        except Exception:
            pass
    finally:
        stage[0] = "shutdown"
        window.close()
        try:
            wait_for(lambda: not window.worker.isRunning(), 90)
            evidence["checks"]["worker_shutdown"] = {"passed": True}
        except Exception as exc:
            evidence["failures"].append(f"Shutdown: {exc}")
            evidence["checks"]["worker_shutdown"] = {"passed": False}
        heartbeat.stop()
        worker_module.EventManager = original_event_manager
        user_database_after = hashlib.sha256(user_database.read_bytes()).hexdigest() if user_database.exists() else None
        evidence["checks"]["user_database_unchanged"] = {"passed": user_database_before == user_database_after}
        gaps = [(b[1] - a[1]) * 1000 for a, b in zip(heartbeats, heartbeats[1:]) if a[0] == b[0]]
        all_gaps = [(b[1] - a[1]) * 1000 for a, b in zip(heartbeats, heartbeats[1:])]
        per_stage = {}
        for name in sorted({point[0] for point in heartbeats}):
            values = [(b[1] - a[1]) * 1000 for a, b in zip(heartbeats, heartbeats[1:]) if a[0] == b[0] == name]
            per_stage[name] = {
                "callbacks": sum(point[0] == name for point in heartbeats),
                "mean_gap_ms": statistics.mean(values) if values else None,
                "maximum_gap_ms": max(values) if values else None,
                "p95_gap_ms": sorted(values)[int(.95 * (len(values) - 1))] if values else None,
            }
        evidence["ui_heartbeat"] = {
            "callbacks": len(heartbeats),
            "interval_ms": 10,
            "mean_gap_ms": statistics.mean(gaps) if gaps else None,
            "maximum_gap_ms": max(gaps) if gaps else None,
            "p95_gap_ms": sorted(gaps)[int(.95 * (len(gaps) - 1))] if gaps else None,
            "maximum_gap_including_stage_transitions_ms": max(all_gaps) if all_gaps else None,
            "per_stage": per_stage,
            "note": "Actual Python callbacks while Qt events and the real model worker run. Heavy library imports were measured separately before window display. first_real_video includes model weight loading and first inference. verifier_clip_extraction is test preparation in the GUI test driver, not production source handling. Per-stage gaps exclude stage transitions; the separate overall maximum includes them.",
        }
        evidence["passed"] = not evidence["failures"] and all(item["passed"] for item in evidence["checks"].values())
        path = output / "desktop-verification.json"
        path.write_text(json.dumps(evidence, indent=2))
        print(json.dumps({"passed": evidence["passed"], "evidence": str(path), "checks": len(evidence["checks"]), "display_mode": evidence["display_mode"], "failures": evidence["failures"]}))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
