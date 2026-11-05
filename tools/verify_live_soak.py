#!/usr/bin/env python3
"""Bounded real-camera pipeline observation; no media or detection records saved.

This tool opens the explicitly selected camera and performs real local inference.
A short run records observed memory behavior, not proof of absence of leaks.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Measurements:
    def __init__(self):
        self.count = 0
        self.total_ms = self.minimum_ms = self.maximum_ms = 0.0

    def add(self, value):
        value = float(value)
        self.minimum_ms = min(self.minimum_ms, value) if self.count else value
        self.maximum_ms = max(self.maximum_ms, value)
        self.total_ms += value
        self.count += 1

    def report(self):
        return {"frames": self.count,
                "mean_ms": self.total_ms / self.count if self.count else None,
                "minimum_ms": self.minimum_ms if self.count else None,
                "maximum_ms": self.maximum_ms if self.count else None}


def metadata_fingerprint():
    result = {}
    for name in ("detections.sqlite3", "detections.sqlite3-wal", "detections.sqlite3-shm"):
        path = ROOT / "recordings" / name
        if path.exists():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            result[name] = {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--device", choices=("auto", "cpu", "mps"), default="auto")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--sample-interval", type=float, default=5)
    parser.add_argument("--warmup", type=float, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/camera-soak.json")
    args = parser.parse_args()
    if args.camera < 0 or not math.isfinite(args.seconds) or not 1 <= args.seconds <= 300:
        parser.error("Use a nonnegative camera index and a duration between 1 and 300 seconds")
    if not math.isfinite(args.sample_interval) or not 1 <= args.sample_interval <= args.seconds:
        parser.error("Sample interval must be between one second and the run duration")
    if not math.isfinite(args.warmup) or not 0 <= args.warmup < args.seconds:
        parser.error("Warmup must be nonnegative and shorter than the observation")
    import psutil
    import torch
    from multiprocessing.shared_memory import SharedMemory
    from sentinal.config import AppConfig
    from sentinal.vision.pipeline import VisionPipeline
    from sentinal.vision.types import count_objects
    from sentinal.vision.video_source import SourceSpec

    output = args.output.expanduser().resolve()
    if not output.is_relative_to(ROOT):
        parser.error("Evidence must remain inside the SENTINAL project directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"test": "bounded real-camera and actual model pipeline observation",
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "camera_index": args.camera, "requested_device": args.device,
              "requested_monitor_seconds": args.seconds, "warmup_seconds": args.warmup,
              "sample_interval_seconds": args.sample_interval,
              "mock_inference": False, "media_saved": False, "metadata_recording_enabled": False,
              "frames": 0, "samples": [], "checks": {}, "failures": [],
              "limitations": [
                  "One short run cannot establish long-term leak freedom or thermal stability.",
                  "RSS and MPS allocation observations include allocator caches and persistent model weights.",
                  "Counts are unannotated model outputs, not verified physical-person or bag counts.",
                  "No frames, screenshots, bounding boxes or per-object tracking identities are retained.",
                  "Frame age is measured at analysis completion, not remote encoder-to-display latency.",
              ]}
    pipeline = VisionPipeline(AppConfig(device=args.device))
    parent = psutil.Process()
    child = source = None
    memory_name = None
    before_metadata = metadata_fingerprint()
    overall_latency, warm_latency = Measurements(), Measurements()
    overall_age, warm_age = Measurements(), Measurements()
    counts = {"people": 0, "bags": 0, "tracked": 0, "detections": 0}
    devices = set()
    last_index = 0
    increasing = True
    monitoring_started = None
    next_sample = args.sample_interval
    next_progress = 15.0
    maximum_samples = int(math.ceil(args.seconds / args.sample_interval))

    def memory_sample(elapsed):
        sample = {"elapsed_s": elapsed, "parent_rss_bytes": parent.memory_info().rss,
                  "capture_child_rss_bytes": None, "mps_current_allocated_bytes": None,
                  "mps_driver_allocated_bytes": None}
        if child is not None:
            try:
                sample["capture_child_rss_bytes"] = child.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        if "mps" in devices:
            for function, key in (("current_allocated_memory", "mps_current_allocated_bytes"),
                                  ("driver_allocated_memory", "mps_driver_allocated_bytes")):
                callback = getattr(torch.mps, function, None)
                if callback is not None:
                    try:
                        sample[key] = int(callback())
                    except (RuntimeError, NotImplementedError):
                        pass
        return sample

    try:
        print("Loading the local model and opening the selected real camera…", flush=True)
        startup = time.monotonic()
        from PySide6.QtCore import QCoreApplication
        from sentinal.vision.camera_manager import discover_cameras
        camera_app = QCoreApplication.instance() or QCoreApplication([])
        selected_camera = next((c for c in discover_cameras() if c.index == args.camera), None)
        if selected_camera is None:
            raise RuntimeError("Selected camera unavailable; no other camera will be opened")
        pipeline.start(SourceSpec("camera", selected_camera.index, camera_device_id=selected_camera.device_id, camera_name=selected_camera.name))
        source = pipeline.source
        child = psutil.Process(source.capture.pid)
        memory_name = source._memory.name
        report["startup_to_camera_open_s"] = time.monotonic() - startup
        report["initial_parent_rss_bytes"] = parent.memory_info().rss
        report["initial_capture_child_rss_bytes"] = child.memory_info().rss
        monitoring_started = time.monotonic()
        while time.monotonic() - monitoring_started < args.seconds:
            frame_started = time.monotonic() - monitoring_started
            packet = pipeline.step()
            if packet is None:
                raise RuntimeError("A live source unexpectedly reported end-of-file")
            elapsed = time.monotonic() - monitoring_started
            report["frames"] += 1
            devices.add(packet.device)
            increasing = increasing and packet.frame_index > last_index
            last_index = packet.frame_index
            overall_latency.add(packet.inference_ms)
            overall_age.add(packet.frame_age_ms)
            if frame_started >= args.warmup:
                warm_latency.add(packet.inference_ms)
                warm_age.add(packet.frame_age_ms)
            for key, count in count_objects(packet.detections).items():
                counts[key] = max(counts[key], count)
            report["last_pipeline_fps"] = packet.fps
            report["last_capture_frame_index"] = packet.frame_index
            report["capture_frames_dropped"] = packet.dropped_frames
            report["dimensions"] = [int(packet.frame.shape[1]), int(packet.frame.shape[0])]
            if elapsed >= next_sample and len(report["samples"]) < maximum_samples:
                report["samples"].append(memory_sample(elapsed))
                next_sample += args.sample_interval
            if elapsed >= next_progress:
                print(f"Camera observation {elapsed:.1f}s: {report['frames']} actual frames; device={packet.device}; rolling pipeline={packet.fps:.2f} FPS; vision={packet.inference_ms:.2f} ms; drops={packet.dropped_frames}", flush=True)
                next_progress += 15.0
        report["monitor_wall_s"] = time.monotonic() - monitoring_started
        report["wall_processing_fps"] = report["frames"] / report["monitor_wall_s"]
        report["warm_wall_processing_fps"] = warm_latency.count / max(.001, report["monitor_wall_s"] - args.warmup)
        report["overall_vision_latency"] = overall_latency.report()
        report["warm_vision_latency"] = warm_latency.report()
        report["overall_frame_age_at_analysis"] = overall_age.report()
        report["warm_frame_age_at_analysis"] = warm_age.report()
        report["actual_devices"] = sorted(devices)
        report["maximum_model_counts_observed"] = counts
        report["checks"]["actual_frames_processed"] = report["frames"] > 0
        report["checks"]["fresh_increasing_capture_sequences"] = increasing
        report["checks"]["bounded_memory_sample_count"] = len(report["samples"]) <= maximum_samples
        warm_samples = [sample for sample in report["samples"] if sample["elapsed_s"] >= args.warmup]
        if len(warm_samples) >= 2:
            report["warm_observed_memory_change"] = {
                key: warm_samples[-1][key] - warm_samples[0][key]
                if warm_samples[-1][key] is not None and warm_samples[0][key] is not None else None
                for key in ("parent_rss_bytes", "capture_child_rss_bytes", "mps_current_allocated_bytes", "mps_driver_allocated_bytes")}
    except Exception as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
    finally:
        stopped = time.monotonic()
        try:
            pipeline.stop()
            report["stop_s"] = time.monotonic() - stopped
            report["checks"]["pipeline_source_released"] = pipeline.source is None
            report["checks"]["capture_child_stopped"] = child is None or not child.is_running()
            report["checks"]["capture_handle_released"] = source is None or source.capture is None
            report["checks"]["shared_memory_reference_released"] = source is None or source._memory is None
            if memory_name is not None:
                try:
                    leftover = SharedMemory(name=memory_name)
                except FileNotFoundError:
                    report["checks"]["shared_memory_unlinked"] = True
                else:
                    leftover.close()
                    report["checks"]["shared_memory_unlinked"] = False
            report["checks"]["metadata_database_unchanged"] = metadata_fingerprint() == before_metadata
            report["parent_rss_after_stop_bytes"] = parent.memory_info().rss
        except Exception as exc:
            report["failures"].append(f"Cleanup: {type(exc).__name__}: {exc}")
        report["passed"] = not report["failures"] and bool(report["checks"]) and all(report["checks"].values())
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"passed": report["passed"], "frames": report["frames"],
                          "evidence": str(output), "failures": report["failures"]}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
