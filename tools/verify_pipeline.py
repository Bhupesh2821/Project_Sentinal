#!/usr/bin/env python3
"""Run real local inference and tracking; write reproducible measurement evidence.

No fixture is downloaded and no camera is opened by this tool. Supply an image
and/or an actual recorded video. Synthetic motion is not a real-video fixture.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fixture_info(path, provenance):
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Fixture does not exist: {p}")
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"filename": p.name, "bytes": p.stat().st_size,
            "sha256": digest.hexdigest(), "provenance": provenance}


def latency_summary(values):
    if not values:
        return {"samples": 0}
    ordered = sorted(values)
    return {"samples": len(values), "mean_ms": statistics.fmean(values),
            "median_ms": statistics.median(values),
            "p95_ms": ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))],
            "min_ms": ordered[0], "max_ms": ordered[-1]}


def evaluate_focus_annotations(detections, labels_path, image_shape):
    """Single-fixture same-class greedy IoU matching, explicitly not AP/mAP."""
    classes = {0: "person", 24: "backpack", 26: "handbag", 28: "suitcase"}
    height, width = image_shape[:2]
    annotations = defaultdict(list)
    for row in Path(labels_path).read_text().splitlines():
        if not row.strip():
            continue
        values = row.split()
        if len(values) != 5:
            raise ValueError("COCO fixture label must have class xc yc width height")
        class_id = int(values[0])
        if class_id not in classes:
            continue
        xc, yc, w, h = map(float, values[1:])
        annotations[classes[class_id]].append(((xc - w / 2) * width, (yc - h / 2) * height,
                                              (xc + w / 2) * width, (yc + h / 2) * height))
    def iou(a, b):
        area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - area
        return area / union if union > 0 else 0.0
    counts = {}
    for label in classes.values():
        ground_truth = annotations[label]
        predicted = sorted((d for d in detections if d.label == label), key=lambda d: -d.confidence)
        available = set(range(len(ground_truth)))
        matched = 0
        for detection in predicted:
            candidates = [(iou(detection.bbox, ground_truth[index]), index) for index in available]
            if candidates:
                overlap, index = max(candidates)
                if overlap >= 0.5:
                    available.remove(index)
                    matched += 1
        counts[label] = {"annotated": len(ground_truth), "predicted": len(predicted),
                         "matched_iou_0_5": matched, "unmatched_annotations": len(ground_truth) - matched,
                         "unmatched_predictions": len(predicted) - matched}
    return {"method": "Single image, same-class greedy matching, IoU >=0.5; not AP or a general accuracy estimate",
            "labels": fixture_info(labels_path, "Original COCO128 YOLO annotations"),
            "class_counts": counts}


def benchmark_image(config, image, repeats, evidence_dir, tag, labels_path=None):
    import cv2
    from sentinal.vision.detector import YOLODetector
    detector = YOLODetector(config)
    detector.load()
    # First inference includes backend warmup and is reported separately.
    started = time.perf_counter()
    detector.infer(image)
    warmup_wall_ms = (time.perf_counter() - started) * 1000
    durations, detections = [], ()
    for _ in range(repeats):
        started = time.perf_counter()
        detections = detector.infer(image)
        durations.append((time.perf_counter() - started) * 1000)
    observations = detections
    result = {"requested_device": config.device, "image_size": config.image_size,
              "warmup_wall_ms": warmup_wall_ms,
              "wall_latency": latency_summary(durations),
              "detections": [asdict(item) for item in observations],
              "class_counts": dict(Counter(item.label for item in observations))}
    result["actual_device"] = getattr(detector, "device", "unreported")
    result["fallback_reason"] = detector.fallback_reason
    if labels_path:
        result["focus_annotation_comparison"] = evaluate_focus_annotations(observations, labels_path, image.shape)
    rendered = image.copy()
    for item in observations:
        x1, y1, x2, y2 = map(int, item.bbox)
        cv2.rectangle(rendered, (x1, y1), (x2, y2), (255, 180, 30), 2)
        text = f"{item.label} {item.confidence:.2f}"
        if item.track_id is not None:
            text += f" #{item.track_id}"
        cv2.putText(rendered, text, (x1, max(16, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 230, 200), 1, cv2.LINE_AA)
    out = evidence_dir / f"image-{tag}.jpg"
    if not cv2.imwrite(str(out), rendered):
        raise OSError(f"Cannot write annotated image: {out}")
    result["annotated_image"] = out.name
    return result


def verify_video(config, path, max_frames):
    from sentinal.vision.pipeline import VisionPipeline
    from sentinal.vision.video_source import SourceSpec
    pipeline = VisionPipeline(config)
    per_id_frames = defaultdict(list)
    class_observations = Counter()
    inference_ms, packet_fps, step_wall_s, actual_devices = [], [], [], set()
    simultaneous_max = 0
    frames = 0
    ended = False
    previous_ids = set()
    consecutive_shared = 0
    try:
        pipeline.start(SourceSpec("file", str(path)))
        started = time.perf_counter()
        while frames < max_frames:
            step_started = time.perf_counter()
            packet = pipeline.step()
            step_elapsed = time.perf_counter() - step_started
            if packet is None:
                ended = True
                break
            frames += 1
            step_wall_s.append(step_elapsed)
            ids = {d.track_id for d in packet.detections if d.track_id is not None}
            consecutive_shared += len(previous_ids & ids)
            previous_ids = ids
            simultaneous_max = max(simultaneous_max, len(ids))
            for det in packet.detections:
                class_observations[det.label] += 1
                if det.track_id is not None:
                    per_id_frames[f"{det.label}:{det.track_id}"].append(packet.frame_index)
            inference_ms.append(packet.inference_ms)
            packet_fps.append(packet.fps)
            actual_devices.add(packet.device)
        elapsed = time.perf_counter() - started
    finally:
        pipeline.stop()
    return {
        "requested_device": config.device, "actual_devices": sorted(actual_devices),
        "image_size": config.image_size, "processed_frames": frames,
        "reached_end_of_file": ended,
        "wall_elapsed_s_including_first_inference": elapsed,
        "wall_fps_including_first_inference": frames / elapsed if elapsed else 0,
        "inference_latency": latency_summary(inference_ms),
        "first_inference_ms": inference_ms[0] if inference_ms else None,
        "steady_inference_latency_excluding_first": latency_summary(inference_ms[1:]),
        "steady_wall_fps_excluding_first": (frames - 1) / sum(step_wall_s[1:]) if frames > 1 and sum(step_wall_s[1:]) else 0,
        "last_reported_pipeline_fps": packet_fps[-1] if packet_fps else 0,
        "class_observations_across_frames": dict(class_observations),
        "unique_class_track_pairs": len(per_id_frames),
        "max_simultaneous_assigned_ids": simultaneous_max,
        "consecutive_shared_id_observations": consecutive_shared,
        "track_frame_indices": dict(per_id_frames),
        "limits": "Repeated IDs demonstrate numerical association only. Identity correctness, ID switches, and long-occlusion recovery require annotated visual review.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--labels", type=Path, help="Optional original YOLO .txt annotations for --image")
    parser.add_argument("--video", type=Path)
    parser.add_argument("--weights", type=Path, default=ROOT / "models/yolo11n.pt")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/pipeline.json")
    parser.add_argument("--provenance", default="User supplied local fixture; provenance not specified")
    parser.add_argument("--devices", nargs="+", choices=("cpu", "mps", "auto"), default=["cpu", "mps"])
    parser.add_argument("--sizes", nargs="+", type=int, choices=(320, 480, 640, 960), default=[320, 480, 640])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--frames", type=int, default=90)
    args = parser.parse_args()
    if not args.image and not args.video:
        parser.error("Supply --image and/or --video; this tool never substitutes fake input")
    if args.labels and not args.image:
        parser.error("--labels requires --image")
    if args.repeats < 1 or args.frames < 1:
        parser.error("--repeats and --frames must be positive")

    # Import SENTINAL first so offline/autoinstall/privacy environment settings
    # are established before importing any Ultralytics initialization code.
    from sentinal.config import AppConfig
    import cv2
    import torch
    import ultralytics

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "platform": platform.platform(), "machine": platform.machine(),
              "python": platform.python_version(), "opencv": cv2.__version__,
              "torch": torch.__version__, "ultralytics": ultralytics.__version__,
              "mps_built": torch.backends.mps.is_built(),
              "mps_available": torch.backends.mps.is_available(),
              "model": fixture_info(args.weights, "Local pretrained weights"),
              "image_runs": [], "video_runs": [], "failures": [], "skipped": []}
    image = None
    if args.image:
        report["image_fixture"] = fixture_info(args.image, args.provenance)
        image = cv2.imread(str(args.image))
        if image is None:
            parser.error(f"Cannot decode image: {args.image}")
    if args.video:
        report["video_fixture"] = fixture_info(args.video, args.provenance)
    for device in args.devices:
        if device == "mps" and not torch.backends.mps.is_available():
            report["skipped"].append({"device": "mps", "reason": "PyTorch reports MPS unavailable"})
            continue
        for size in args.sizes:
            config = AppConfig(model_path=str(args.weights.resolve()), device=device, image_size=size)
            for kind, fixture in (("image", image), ("video", args.video)):
                if fixture is None:
                    continue
                try:
                    result = (benchmark_image(config, fixture, args.repeats, args.output.parent,
                                              f"{args.image.stem}-{device}-{size}", args.labels) if kind == "image" else
                              verify_video(config, fixture, args.frames))
                    report[f"{kind}_runs"].append(result)
                    print(f"{kind} {device} {size}: completed", flush=True)
                except Exception as exc:
                    report["failures"].append({"fixture": kind, "device": device,
                                               "image_size": size,
                                               "error": f"{type(exc).__name__}: {exc}"})
                    print(f"{kind} {device} {size}: {type(exc).__name__}: {exc}", flush=True)
                args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"Evidence written to {args.output}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
