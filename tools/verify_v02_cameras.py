#!/usr/bin/env python3
"""Native selected-camera V0.2 inference test; never persist camera pixels/objects.

This deliberately opens each available Mac/iPhone camera through Start controls.
It validates capture and actual model execution, not hazard recognition accuracy.
No weapons/fire are staged. Recording, evidence, audio and notifications stay off.
"""
from datetime import datetime,timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def storage_fingerprints():
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'recordings').rglob('*') if p.is_file() and p.suffix in {'.sqlite3','.db','.jpg','.jpeg','.png','.mp4','.avi'}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='docs/evidence/v021-2026-11-03/native-cameras.json')
    args=parser.parse_args()
    import psutil
    report={'test':'Native selected Mac/iPhone cameras through V0.2 real inference; no camera images or object records saved',
        'created_utc':datetime.now(timezone.utc).isoformat(),'camera_images_saved':False,
        'camera_object_records_saved':False,'microphone_opened':False,'audio_enabled':False,
        'external_notifications_enabled':False,'hazard_accuracy_tested':False,'checks':{},'cycles':[],
        'blocked':[],'passed':False}
    output=(ROOT/args.output).resolve()
    if not output.is_relative_to(ROOT):raise ValueError('Evidence must remain inside project')
    window=app=None
    before=storage_fingerprints()
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    try:
        for process in psutil.process_iter(['pid','name','cmdline']):
            try:
                if process.pid==os.getpid() or 'python' not in (process.info['name'] or '').lower():continue
                arguments=process.info['cmdline'] or []
                if any(Path(a).name=='main.py' for a in arguments) and (str(ROOT) in ' '.join(arguments) or Path(process.cwd())==ROOT):
                    report['blocked'].append('Another SENTINAL desktop process is open; no competing camera test was started.')
                    return 2
            except (psutil.Error,OSError):continue
        from PySide6.QtWidgets import QApplication
        from sentinal.application import prepare_runtime
        from sentinal.config import AppConfig
        from sentinal.core.v02_settings import V02Settings
        from sentinal.interface.main_window import MainWindow
        from sentinal.interface.themes import STYLESHEET
        prepare_runtime()
        app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLESHEET)
        report['qt_platform']=app.platformName()
        check('native_cocoa_interface',app.platformName()=='cocoa')
        window=MainWindow(AppConfig(image_size=480));window.show();app.processEvents()
        window.hazard_settings=V02Settings(detectors=('weapons','fire_smoke'),confidence=.6)
        check('no_capture_on_launch',window.worker.pipeline is None)
        check('recording_and_audio_disabled',not any(toggle.isChecked() for toggle in
            (window.metadata_toggle,window.incident_record_toggle,window.evidence_toggle,window.audio_toggle,window.desktop_toggle)))
        window.hazards_toggle.setChecked(True)
        def pump(predicate,timeout=25):
            end=time.monotonic()+timeout
            while time.monotonic()<end:
                app.processEvents()
                if predicate():return
                time.sleep(.005)
            raise TimeoutError('Selected camera did not deliver required live inference in time')
        identities=set();base_model=None;specialized_models=None
        for category in ('Mac camera','Phone camera','Mac camera'):
            window.refresh_cameras()
            device=next((window.camera_combo.itemData(i) for i in range(window.camera_combo.count())
                if getattr(window.camera_combo.itemData(i),'category',None)==category),None)
            if device is None:
                report['blocked'].append(category+' was not enumerated at its explicit test step; no substitute was opened.');continue
            item={'category':category,'stable_id_sha256':hashlib.sha256(device.device_id.encode()).hexdigest(),
                'frames_received':0,'specialized_samples':0,'passed':False}
            report['cycles'].append(item)
            index=next(i for i in range(window.camera_combo.count()) if getattr(window.camera_combo.itemData(i),'device_id',None)==device.device_id)
            window.source_type.setCurrentIndex(0);window.camera_combo.setCurrentIndex(index)
            window.start_button.click();started=time.monotonic();source=None
            try:
                pump(lambda:window.last_packet is not None or window._state=='error' and not window._busy,35)
                if window._state=='error':
                    item['blocked']='Selected hardware could not open or deliver inference. Check permission, connection or competing camera use.'
                    report['blocked'].append(category+': '+item['blocked']);continue
                source=window.worker.pipeline.source
                check('exact_selection_'+str(len(report['cycles'])),window._current_spec.camera_device_id==device.device_id)
                frame_keys=set();timings=[];fps=[];ages=[];health={};live_started=time.monotonic()
                hazard_timings={'weapons':[],'fire_smoke':[]}
                while len(frame_keys)<8 or time.monotonic()-live_started<10 or not all(health.get(key,{}).get('status')=='active' for key in ('weapons','fire_smoke')):
                    pump(lambda:window._state=='error' and not window._busy or window.last_packet is not None and (window.last_packet.session_id,window.last_packet.frame_index) not in frame_keys,20)
                    if window._state=='error' and not window._busy:raise ConnectionError('Selected live feed stopped delivering fresh frames; application released the source without substituting another camera.')
                    packet=window.last_packet;key=(packet.session_id,packet.frame_index)
                    frame_keys.add(key);timings.append(packet.inference_ms);fps.append(packet.fps);ages.append(packet.frame_age_ms)
                    item['frames_received']=len(frame_keys)
                    check('source_identity_matches_'+str(len(report['cycles'])),packet.source==device.name)
                    if packet.hazard_sampled:
                        item['specialized_samples']+=1
                        for module in hazard_timings:
                            info=packet.detector_health.get(module,{})
                            if info.get('status')=='active' and info.get('latency_ms') is not None:hazard_timings[module].append(info['latency_ms'])
                        health={key:{name:value for name,value in entry.items() if name in {'status','device','model_id','model_version','latency_ms'}} for key,entry in packet.detector_health.items()}
                    item['detector_health']=health
                    if time.monotonic()-started>30:raise TimeoutError('Specialized models did not become active on the selected camera')
                item.update(frames_received=len(frame_keys),shape=list(packet.frame.shape),device=packet.device,
                    inference_ms_median=statistics.median(timings),inference_ms_max=max(timings),
                    measured_fps_median=statistics.median(fps),frame_age_ms_median=statistics.median(ages),
                    detector_health=health,elapsed_s=time.monotonic()-started,live_observation_s=time.monotonic()-live_started,
                    specialized_inference_ms_median={key:statistics.median(values) if values else None for key,values in hazard_timings.items()})
                identities.add(item['stable_id_sha256'])
                identity=id(window.worker.pipeline.detector.model)
                if base_model is None:base_model=identity
                check('base_model_reused_'+str(len(report['cycles'])),identity==base_model)
                suite=window.worker.pipeline.hazard_suite
                models=tuple((key,id(value['model'])) for key,value in suite._models.items() if isinstance(value,dict))
                if specialized_models is None:specialized_models=models
                check('specialized_models_reused_'+str(len(report['cycles'])),models==specialized_models)
                item['passed']=True
            except (TimeoutError,AssertionError,ConnectionError) as exc:
                item['failure']=str(exc)
            finally:
                stopped=time.monotonic();window.stop_button.click()
                pump(lambda:window._state in {'stopped','error'},12)
                item['stop_s']=time.monotonic()-stopped
                item['resources_released']=(window.worker.pipeline is None or window.worker.pipeline.source is None) and (source is None or source.capture is None and source._memory is None)
                item['passed']=item['passed'] and item['resources_released']
        report['both_device_categories_tested']=len(identities)==2
        check('all_started_cycles_release',all(item['resources_released'] for item in report['cycles']))
        check('storage_unchanged',storage_fingerprints()==before)
        check('recording_and_audio_stay_disabled',not any(toggle.isChecked() for toggle in
            (window.metadata_toggle,window.incident_record_toggle,window.evidence_toggle,window.audio_toggle,window.desktop_toggle)))
        report['passed']=bool(report['cycles']) and all(item['passed'] for item in report['cycles']) and all(report['checks'].values())
    except Exception as exc:report['failure']=str(exc) if isinstance(exc,(AssertionError,TimeoutError)) else type(exc).__name__
    finally:
        if window is not None:
            window.close()
            end=time.monotonic()+15
            while window.worker.isRunning() or window._incident_worker is not None and window._incident_worker.isRunning():
                app.processEvents();time.sleep(.005)
                if time.monotonic()>end:break
            report['workers_released']=not window.worker.isRunning() and (window._incident_worker is None or not window._incident_worker.isRunning())
            window.close();app.processEvents()
            report['passed']=report['passed'] and report['workers_released']
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
