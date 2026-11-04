#!/usr/bin/env python3
"""Explicit on-device camera acceptance through SENTINAL's native desktop UI.

Running this script activates the chosen camera for five short monitoring
sessions by default. It uses the real YOLO/ByteTrack worker. No camera images,
screenshots, video, audio, bounding boxes or individual track IDs are saved.
Optional detection metadata stays disabled. JSON evidence contains aggregate
counts, timing, frame dimensions and resource/session checks only.

    .venv/bin/python tools/verify_camera_desktop.py --camera 0 --device auto

The native macOS desktop and camera permission for the launcher are required.
--help does not load vision libraries, create a window or open a camera.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import time
import traceback
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def capture_is_open(capture):
    """Support synchronous captures and closed multiprocessing handles."""
    if capture is None:
        return False
    try:
        return bool(capture.is_alive()) if hasattr(capture, "is_alive") else bool(capture.isOpened())
    except (ValueError, RuntimeError):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0, help="Actual camera index to activate")
    parser.add_argument("--device", choices=("auto", "cpu", "mps"), default="auto")
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--frames", type=int, default=6, help="Minimum distinct displayed frames per cycle")
    parser.add_argument("--output", default=str(ROOT / "docs/evidence/camera-desktop-native.json"))
    args = parser.parse_args(argv)
    if args.camera < 0 or args.cycles < 1 or args.frames < 1:
        parser.error("Camera index must be nonnegative; cycles and frames must be positive")

    print("Preparing local vision libraries before the native camera test…", flush=True)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from sentinal.application import prepare_runtime
    from sentinal.config import AppConfig
    from sentinal.core.logger import configure_logging
    from sentinal.interface.main_window import MainWindow
    from sentinal.interface.themes import STYLESHEET
    from sentinal.vision.types import count_objects

    configure_logging()
    runtime_preparation = prepare_runtime()
    evidence = {
        "test": "native Qt camera start/stop with real YOLO/ByteTrack worker",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "camera_index": args.camera,
        "requested_device": args.device,
        "requested_cycles": args.cycles,
        "minimum_displayed_frames_per_cycle": args.frames,
        "mock_inference": False,
        "media_saved": False,
        "screenshots_saved": False,
        "bounding_boxes_saved": False,
        "track_ids_saved": False,
        "metadata_enabled": False,
        "runtime_preparation": runtime_preparation,
        "checks": {},
        "cycles": [],
        "failures": [],
        "limitations": [
            "Counts report model observations in this camera view; this test does not establish bag-detection accuracy.",
            "Camera disconnect and permission denial are not induced by this test.",
            "Pipeline FPS includes capture, detection and tracking; excludes rendering. Observed display FPS includes UI polling.",
        ],
    }
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setApplicationName("SENTINAL Camera Acceptance")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    evidence["qt_platform"] = app.platformName()
    window = MainWindow(AppConfig(device=args.device))
    window.show()
    stage = ["startup"]
    heartbeats = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeats.append((stage[0], time.monotonic())))
    timer.start()
    observed = {}
    source_references = []
    metadata_baseline = None
    pipeline_identity = None
    model_identity = None

    def check(name, condition, detail=None):
        evidence["checks"][name] = {"passed": bool(condition), "detail": detail}
        if not condition:
            raise AssertionError(name)

    def metadata_count():
        database = ROOT / "recordings/detections.sqlite3"
        if not database.exists():
            return 0
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=1) as connection:
            return connection.execute("SELECT COUNT(*) FROM detections").fetchone()[0]

    def observe():
        packet = window.last_packet
        if packet is None:
            return
        key = (packet.session_id, packet.frame_index)
        if key in observed:
            return
        observed[key] = {
            "observed_monotonic": time.monotonic(),
            "stage": stage[0],
            "session_id": packet.session_id,
            "frame_index": packet.frame_index,
            "width": int(packet.frame.shape[1]),
            "height": int(packet.frame.shape[0]),
            "device": packet.device,
            "pipeline_fps": packet.fps,
            "vision_ms": packet.inference_ms,
            "average_vision_ms": packet.average_inference_ms,
            "frame_age_ms": getattr(packet, "frame_age_ms", 0.0),
            "dropped_frames": getattr(packet, "dropped_frames", 0),
            "counts": count_objects(packet.detections),
        }

    def wait_for(predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            observe()
            if predicate():
                return
            if window._state == "error" and stage[0] != "shutdown":
                raise AssertionError(f"Camera monitoring failed: {window.error_banner.text()}")
            time.sleep(.005)
        raise AssertionError(f"Timed out during {stage[0]}: {window._state}; {window.error_banner.text()}")

    try:
        wait_for(lambda: len(heartbeats) >= 10, 5)
        check("native_macos_desktop", app.platformName() == "cocoa", app.platformName())
        check("desktop_visible", window.isVisible())
        check("camera_inactive_before_start", window.worker.pipeline is None)
        check("metadata_disabled_before_start", not window.metadata_toggle.isChecked())
        metadata_baseline = metadata_count()
        window.source_type.setCurrentIndex(0)
        camera_position = next((i for i in range(window.camera_combo.count()) if getattr(window.camera_combo.itemData(i), "index", None) == args.camera), -1)
        check("selected_camera_enumerated", camera_position >= 0)
        window.camera_combo.setCurrentIndex(camera_position)
        evidence["camera_display_name"] = window.camera_combo.currentText()

        for cycle_number in range(1, args.cycles + 1):
            stage[0] = f"camera_cycle_{cycle_number}"
            cycle_stage = stage[0]
            print(f"Native camera cycle {cycle_number}/{args.cycles}: starting real monitoring…", flush=True)
            started = time.monotonic()
            window.start_button.click()
            wait_for(lambda: sum(item["stage"] == cycle_stage for item in observed.values()) >= args.frames,
                     60 if cycle_number == 1 else 45)
            packet = window.last_packet
            source = window.worker.pipeline.source
            capture = source.capture
            source_references.append((source, capture))
            check(f"cycle_{cycle_number}_source_open", source.state == "open" and capture_is_open(capture))
            check(f"cycle_{cycle_number}_isolated_native_capture", hasattr(capture, "is_alive"))
            check(f"cycle_{cycle_number}_bounded_pixel_mailbox", source._memory is not None and source._memory.size == 1920 * 1920 * 3)
            check(f"cycle_{cycle_number}_camera_source", source.spec.kind == "camera" and source.spec.value == args.camera)
            check(f"cycle_{cycle_number}_valid_session_uuid", UUID(packet.session_id).version == 4)
            check(f"cycle_{cycle_number}_real_frames", packet.frame.shape[0] > 0 and packet.frame.shape[1] > 0)
            check(f"cycle_{cycle_number}_video_panel_received_frame", window.video_panel._packet is packet and not window.video_panel._image.isNull())
            check(f"cycle_{cycle_number}_measured_metrics", packet.fps > 0 and packet.average_inference_ms > 0)
            check(f"cycle_{cycle_number}_actual_device", packet.device in {"cpu", "mps"}, packet.device)
            check(f"cycle_{cycle_number}_metadata_stays_off", not window.metadata_toggle.isChecked() and not window.worker._metadata_enabled)
            current_pipeline_identity = id(window.worker.pipeline)
            current_model_identity = id(window.worker.pipeline.detector.model)
            if pipeline_identity is None:
                pipeline_identity = current_pipeline_identity
                model_identity = current_model_identity
            check(f"cycle_{cycle_number}_persistent_pipeline", current_pipeline_identity == pipeline_identity)
            check(f"cycle_{cycle_number}_persistent_model", current_model_identity == model_identity)
            frames = [item for item in observed.values() if item["stage"] == cycle_stage]
            elapsed_to_frames = time.monotonic() - started
            stage[0] = f"camera_stop_{cycle_number}"
            stop_started = time.monotonic()
            window.stop_button.click()
            wait_for(lambda: window._state == "stopped", 20)
            check(f"cycle_{cycle_number}_pipeline_source_released", window.worker.pipeline.source is None)
            check(f"cycle_{cycle_number}_capture_released", source.state == "closed" and source.capture is None and not capture_is_open(capture))
            check(f"cycle_{cycle_number}_shared_memory_released", source._memory is None)
            check(f"cycle_{cycle_number}_controls_restored", window.start_button.isEnabled() and not window.stop_button.isEnabled())
            check(f"cycle_{cycle_number}_worker_still_available", window.worker.isRunning())
            display_elapsed = frames[-1]["observed_monotonic"] - frames[0]["observed_monotonic"]
            cycle = {
                "cycle": cycle_number,
                "session_id": packet.session_id,
                "displayed_frames_observed": len(frames),
                "last_source_frame_index": packet.frame_index,
                "start_to_required_frames_s": elapsed_to_frames,
                "safe_stop_s": time.monotonic() - stop_started,
                "actual_devices": sorted({frame["device"] for frame in frames}),
                "dimensions": sorted({(frame["width"], frame["height"]) for frame in frames}),
                "mean_vision_ms": statistics.mean(frame["vision_ms"] for frame in frames),
                "last_rolling_vision_ms": frames[-1]["average_vision_ms"],
                "last_pipeline_fps": frames[-1]["pipeline_fps"],
                "maximum_capture_frames_dropped": max(frame["dropped_frames"] for frame in frames),
                "maximum_frame_age_at_analysis_ms": max(frame["frame_age_ms"] for frame in frames),
                "observed_display_fps": (len(frames) - 1) / display_elapsed if display_elapsed > 0 else None,
                "maximum_counts_observed": {key: max(frame["counts"][key] for frame in frames) for key in frames[0]["counts"]},
                "source_released": True,
                "frames": [{key: value for key, value in frame.items() if key not in {"observed_monotonic", "stage", "session_id"}} for frame in frames],
            }
            evidence["cycles"].append(cycle)
            print(f"Cycle {cycle_number}: {len(frames)} displayed frames, {cycle['last_pipeline_fps']:.2f} pipeline FPS, {cycle['last_rolling_vision_ms']:.2f} ms vision latency; camera released.", flush=True)

        sessions = [cycle["session_id"] for cycle in evidence["cycles"]]
        check("fresh_session_per_restart", len(set(sessions)) == args.cycles)
        check("all_requested_cycles_completed", len(evidence["cycles"]) == args.cycles)
        check("camera_metadata_not_persisted", metadata_count() == metadata_baseline)
    except Exception as exc:
        evidence["failures"].append(str(exc))
        evidence["technical_error"] = traceback.format_exc()
    finally:
        stage[0] = "shutdown"
        window.close()
        try:
            wait_for(lambda: not window.worker.isRunning(), 45)
            evidence["checks"]["worker_shutdown"] = {"passed": True}
            evidence["checks"]["all_captures_released_at_shutdown"] = {
                "passed": all(source.capture is None and not capture_is_open(capture) for source, capture in source_references),
            }
            evidence["checks"]["source_released_at_shutdown"] = {
                "passed": window.worker.pipeline is None or window.worker.pipeline.source is None,
            }
            if metadata_baseline is not None:
                evidence["checks"]["metadata_unchanged_after_shutdown"] = {"passed": metadata_count() == metadata_baseline}
        except Exception as exc:
            evidence["failures"].append(f"Shutdown: {exc}")
            evidence["checks"]["worker_shutdown"] = {"passed": False}
        timer.stop()
        per_stage = {}
        for name in sorted({point[0] for point in heartbeats}):
            gaps = [(b[1] - a[1]) * 1000 for a, b in zip(heartbeats, heartbeats[1:]) if a[0] == b[0] == name]
            per_stage[name] = {
                "callbacks": sum(point[0] == name for point in heartbeats),
                "mean_gap_ms": statistics.mean(gaps) if gaps else None,
                "maximum_gap_ms": max(gaps) if gaps else None,
                "p95_gap_ms": sorted(gaps)[int(.95 * (len(gaps) - 1))] if gaps else None,
            }
        monitoring_callbacks = sum(item["callbacks"] for name, item in per_stage.items() if name.startswith("camera_cycle_"))
        evidence["ui_heartbeat"] = {
            "interval_ms": 10, "callbacks": len(heartbeats),
            "monitoring_callbacks": monitoring_callbacks, "per_stage": per_stage,
            "note": "Actual Qt timer callbacks while the real camera/model worker runs. Stage gaps omit transitions. Cold library preparation precedes window display.",
        }
        evidence["checks"]["ui_heartbeat_during_camera_inference"] = {"passed": monitoring_callbacks > 10}
        evidence["passed"] = not evidence["failures"] and all(item["passed"] for item in evidence["checks"].values())
        output.write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps({"passed": evidence["passed"], "evidence": str(output), "checks": len(evidence["checks"]), "cycles": len(evidence["cycles"]), "failures": evidence["failures"], "media_saved": False}), flush=True)
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
