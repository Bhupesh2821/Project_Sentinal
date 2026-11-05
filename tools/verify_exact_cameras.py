#!/usr/bin/env python3
"""Intentionally capture selected Mac/iPhone frames; never save camera pixels.

This validates capture/selection/release, not detector accuracy. Missing-camera
checks must fail without opening another device. All reports stay in project.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sentinal.vision.camera_manager import discover_cameras
from sentinal.vision.live_capture import LiveVideoSource
from sentinal.vision.video_source import SourceSpec, VideoSourceError


def main():
    from PySide6.QtCore import QCoreApplication
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', choices=('builtin', 'phone', 'both'), default='builtin')
    parser.add_argument('--output', default='docs/evidence/camera-selection-2026-10-28/capture.json')
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError('Evidence must remain inside Project Sentinal')
    app = QCoreApplication.instance() or QCoreApplication([])
    devices = discover_cameras()
    selected = [d for d in devices if
                (args.device in ('builtin', 'both') and d.is_builtin) or
                (args.device in ('phone', 'both') and d.category == 'Phone camera')]
    report = {'test': 'Actual exact-identity camera capture; no camera media saved',
              'device_option': args.device, 'devices_seen': len(devices),
              'camera_images_saved': False, 'microphone_opened': False,
              'detector_tested': False, 'cycles': [], 'checks': {}, 'passed': False}
    try:
        if not selected:
            raise RuntimeError('Requested physical camera was not enumerated')
        for device in selected:
            for cycle in range(2):
                source = LiveVideoSource(SourceSpec('camera', device.index,
                    camera_device_id=device.device_id, camera_name=device.name),
                    open_timeout_ms=8000, read_timeout_ms=3000)
                item = {'category': device.category, 'stable_id_sha256': hashlib.sha256(device.device_id.encode()).hexdigest(),
                        'cycle': cycle + 1, 'frames_received': 0, 'shapes': [], 'passed': False}
                report['cycles'].append(item)
                try:
                    started = monotonic()
                    source.open()
                    item['open_s'] = monotonic() - started
                    for _ in range(12):
                        frame = source.read()
                        assert frame is not None and frame.ndim == 3 and frame.shape[2] == 3
                        item['frames_received'] += 1
                        shape = list(frame.shape)
                        if shape not in item['shapes']:
                            item['shapes'].append(shape)
                        del frame
                    item['passed'] = True
                finally:
                    started = monotonic()
                    source.close()
                    item['stop_s'] = monotonic() - started
                    item['resources_released'] = source.capture is None and source._memory is None
                    item['passed'] = item['passed'] and item['resources_released']
        missing = LiveVideoSource(SourceSpec('camera', 0, camera_device_id='00', camera_name='Unavailable selected camera'))
        try:
            missing.open()
            raise AssertionError('Missing selected device unexpectedly opened')
        except VideoSourceError as exc:
            report['checks']['missing_device_fails_closed'] = 'no longer available' in str(exc)
            report['missing_device_message'] = str(exc)
        finally:
            missing.close()
        report['checks']['all_cycles_released'] = all(c['resources_released'] for c in report['cycles'])
        report['checks']['each_selected_camera_has_distinct_identity'] = len({c['stable_id_sha256'] for c in report['cycles']}) == len(selected)
        report['passed'] = all(report['checks'].values()) and all(c['passed'] for c in report['cycles'])
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        report['error'] = str(exc) if isinstance(exc, (VideoSourceError, AssertionError, RuntimeError)) else 'Camera verification failed'
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
