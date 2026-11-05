"""Explicit native Mac/iPhone GUI and actual local-model integration checks.
Only public recorded footage may be saved as screenshots. No camera pixels,
per-object camera metadata, or microphone data are persisted.
"""
from pathlib import Path
import hashlib
import json
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sentinal.config import AppConfig
from sentinal.application import prepare_runtime
from sentinal.interface.main_window import MainWindow
from sentinal.interface.catalog_dialog import CatalogDialog
from sentinal.interface.themes import STYLESHEET
from sentinal.vision.types import count_objects


def main():
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    app.setStyle('Fusion'); app.setStyleSheet(STYLESHEET)
    output = ROOT / 'docs/evidence/camera-cctv-catalog-2026-10-28'
    output.mkdir(parents=True, exist_ok=True)
    report = {'test': 'Native exact-camera and expanded-model dashboard integration',
              'checks': {}, 'camera_cycles': [], 'camera_images_saved': False,
              'camera_object_records_saved': False, 'microphone_opened': False,
              'physical_cctv_tested': False, 'blocked': [], 'passed': False}
    def fingerprints():
        return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (ROOT/'recordings').glob('*.sqlite3*') if p.is_file()}
    before = fingerprints()
    def check(name, value):
        report['checks'][name] = bool(value)
        if not value: raise AssertionError(name)
    def wait(predicate, timeout=35):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            if predicate(): return
            time.sleep(.005)
        raise AssertionError('Timed out waiting for dashboard transition')
    prepare_runtime()
    window = MainWindow(AppConfig())
    window.show(); app.processEvents()
    try:
        check('standby_no_capture_or_model', window.worker.pipeline is None)
        check('metadata_disabled', not window.metadata_toggle.isChecked())
        cameras = [window.camera_combo.itemData(i) for i in range(window.camera_combo.count())]
        cameras = [d for d in cameras if d is not None]
        selected = window.camera_combo.currentData()
        check('initial_choice_is_builtin', selected is not None and selected.is_builtin)
        tested = set()
        model_identity = None
        sessions = set()
        for category in ('Mac camera', 'Phone camera', 'Mac camera'):
            device = next((d for d in cameras if d.category == category), None)
            if device is None:
                report['blocked'].append(category + ' was not available during this GUI run; exact-capture evidence is separate')
                continue
            check(category.replace(' ','_')+'_enumerated', device is not None)
            index = next(i for i in range(window.camera_combo.count())
                         if getattr(window.camera_combo.itemData(i), 'device_id', None) == device.device_id)
            window.source_type.setCurrentIndex(0)
            window.camera_combo.setCurrentIndex(index)
            window.start_button.click()
            wait(lambda: window.last_packet is not None or window._state == 'error')
            check('camera_running_'+str(len(report['camera_cycles'])), window._state == 'running')
            check('exact_spec_'+str(len(report['camera_cycles'])), window._current_spec.camera_device_id == device.device_id)
            first = window.last_packet
            session = first.session_id
            check('unique_session_'+str(len(report['camera_cycles'])), session not in sessions)
            sessions.add(session)
            observed = []
            last = -1
            while len(observed) < 8:
                wait(lambda: window.last_packet is not None and window.last_packet.frame_index != last)
                packet = window.last_packet
                last = packet.frame_index
                check('selected_source_label_'+str(len(report['camera_cycles'])), packet.source == device.name)
                observed.append({'inference_ms': packet.inference_ms, 'frame_age_ms': packet.frame_age_ms})
            actual_model = id(window.worker.pipeline.detector.model)
            if model_identity is None: model_identity = actual_model
            check('same_loaded_model_'+str(len(report['camera_cycles'])), actual_model == model_identity)
            source = window.worker.pipeline.source
            started = time.monotonic(); window.stop_button.click()
            wait(lambda: window._state == 'stopped')
            elapsed = time.monotonic()-started
            check('camera_resources_released_'+str(len(report['camera_cycles'])), source.capture is None and source._memory is None)
            report['camera_cycles'].append({'category': category, 'displayed_frames_checked': len(observed),
                'mean_inference_ms': sum(x['inference_ms'] for x in observed)/len(observed),
                'stop_s': elapsed, 'source_shape': list(first.frame.shape), 'device': first.device})
            tested.add(category)
        report['both_camera_categories_tested'] = len(tested) == 2
        window.model_combo.setCurrentIndex(1)
        window.filter_combo.setCurrentIndex(1)
        window.load_video(ROOT/'tests/fixtures/vtest.avi')
        window.start_button.click()
        wait(lambda: window.last_packet is not None and window._state == 'running')
        wait(lambda: window.last_packet is not None and any(d.label=='person' and d.track_id is not None for d in window.last_packet.detections))
        packet = window.last_packet
        check('expanded_model_actually_loaded', window.worker.pipeline.detector.config.weights.name == 'yolov8n-oiv7.pt')
        check('expanded_packet_model_provenance', packet.model_name == 'yolov8n-oiv7.pt')
        check('expanded_actual_person_and_tracks', any(d.label=='person' and d.track_id is not None for d in packet.detections))
        check('expanded_counts_normalized', int(window.statistics.values['people'].text()) == count_objects(packet.detections)['people'])
        report['recorded_video'] = {'model': packet.model_name, 'device': packet.device,
            'people': count_objects(packet.detections)['people'], 'inference_ms': packet.inference_ms}
        check('public_file_screenshot_saved', window.grab().save(str(output/'desktop-expanded-public-video.png')))
        window.stop_button.click(); wait(lambda: window._state == 'stopped')
        dialog = CatalogDialog('models/yolov8n-oiv7.pt', window)
        dialog.show(); dialog.search.setText('helmet'); app.processEvents()
        check('searchable_actual_catalog', dialog.table.rowCount() >= 1)
        check('catalog_screenshot_saved', dialog.grab().save(str(output/'expanded-category-catalog.png')))
        dialog.close()
        window.source_type.setCurrentIndex(2); window.network_setup_button.click(); app.processEvents()
        setup = window._network_dialog
        check('network_setup_opens_without_connecting', setup is not None and not setup.setup_running and window.worker.pipeline.source is None)
        check('network_setup_screenshot_saved', setup.grab().save(str(output/'network-camera-setup.png')))
        setup.close()
        window.model_combo.setCurrentIndex(0)
        window.load_video(ROOT/'tests/fixtures/vtest.avi'); window.start_button.click()
        wait(lambda: window.last_packet is not None and window._state == 'running')
        check('switch_back_to_original_model', window.last_packet.model_name == 'yolo11n.pt')
        window.stop_button.click(); wait(lambda: window._state == 'stopped')
        check('user_detection_database_unchanged', fingerprints() == before)
        report['passed'] = all(report['checks'].values())
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        window.close(); wait(lambda: not window.worker.isRunning())
        report['checks']['worker_shutdown'] = not window.worker.isRunning()
        report['passed'] = report['passed'] and all(report['checks'].values())
        (output/'desktop-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)
    return 0 if report['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
