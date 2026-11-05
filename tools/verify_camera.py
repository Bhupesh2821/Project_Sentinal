#!/usr/bin/env python3
"""Explicit on-device camera acceptance probe. Captures one frame, saves no media.

Run only when intentionally testing camera access. This may trigger a macOS
permission prompt for the launcher. Results contain dimensions/status only.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int)
    parser.add_argument("--enumerate", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/camera.json")
    args = parser.parse_args()
    from PySide6.QtCore import QCoreApplication
    from sentinal.vision.camera_manager import discover_cameras
    from sentinal.vision.video_source import SourceSpec, VideoSource
    app = QCoreApplication.instance() or QCoreApplication([])
    cameras = discover_cameras()
    result = {"timestamp": datetime.now(timezone.utc).isoformat(),
              "cameras": [asdict(c) for c in cameras], "media_saved": False,
              "enumeration_is_capture_proof": False, "passed": False}
    source = None
    if args.enumerate:
        result["passed"] = True
    else:
        selected = next((c for c in cameras if c.index == args.index), None) if args.index is not None else next((c for c in cameras if c.is_builtin), None)
        if selected is None:
            parser.error("The selected camera is unavailable. Enumerate first and explicitly choose a named camera; no default will open.")
        result["attempted_index"] = selected.index
        result["selected_name"] = selected.name
        source = VideoSource(SourceSpec("camera", selected.index, camera_device_id=selected.device_id, camera_name=selected.name))
        started = time.perf_counter()
        try:
            source.open()
            result["opened"] = source.state == "open"
            frame = source.read()
            result["frame_read"] = frame is not None
            if frame is not None:
                result["frame_shape"] = list(frame.shape)
                del frame
            result["source_time_s"] = source.source_time_s
            result["reported_source_fps"] = source.fps
            result["passed"] = bool(result["frame_read"])
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["failure_state"] = source.state
        finally:
            source.close()
            result["final_state"] = source.state
            result["capture_released"] = source.capture is None
            result["wall_ms"] = (time.perf_counter() - started) * 1000
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
