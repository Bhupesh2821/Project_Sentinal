#!/usr/bin/env python3
"""Deny Python network connections/DNS during a real local inference run.

This checks this execution path, not a system-wide packet capture. Run after
installation with local model/fixture files. It saves metadata only, no frames.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=ROOT / "tests/fixtures/000000000315.jpg")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/offline.json")
    args = parser.parse_args()
    attempts = []

    def deny(event, values):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.sendto"}:
            # Keep only event names; never serialize video data or credentials.
            attempts.append(event)
            raise PermissionError("Network intentionally disabled for SENTINAL verification")

    sys.addaudithook(deny)
    result = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "method": "Python audit hook rejects DNS, socket.connect and socket.sendto before imports",
              "limitations": "Verifies this Python inference path; not an OS-wide network packet capture.",
              "fixture": args.image.name, "network_attempts": attempts, "passed": False}
    try:
        import sentinal
        import cv2
        from ultralytics.utils import ONLINE, SETTINGS
        from ultralytics.utils.events import events
        from sentinal.config import AppConfig
        from sentinal.vision.detector import YOLODetector
        image = cv2.imread(str(args.image))
        if image is None:
            raise ValueError("Offline inference fixture could not be decoded")
        detector = YOLODetector(AppConfig(device="cpu"))
        started = time.perf_counter()
        detector.load()
        detections = detector.infer(image)
        result.update({"online_flag": ONLINE, "sync_setting": SETTINGS["sync"],
                       "telemetry_events_enabled": events.enabled,
                       "actual_device": detector.device,
                       "wall_ms_including_load": (time.perf_counter() - started) * 1000,
                       "detections": [asdict(d) for d in detections]})
        result["passed"] = not attempts and not ONLINE and not SETTINGS["sync"] and not events.enabled
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
