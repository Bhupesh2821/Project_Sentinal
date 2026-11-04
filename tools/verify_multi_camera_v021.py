"""Actual two-feed H264 RTSP/shared-model/incident/recovery integration.

Only loopback publishers with licensed public recorded fixtures are used.
No physical camera, camera snapshots, microphone or external service is used.
"""
from dataclasses import replace
from datetime import datetime,timezone
import json
from pathlib import Path
import sys,tempfile,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-name',default='multi-camera-rtsp.json')
    args=parser.parse_args()
    if Path(args.report_name).name!=args.report_name or not args.report_name.endswith('.json'):
        parser.error('Use a simple JSON report filename')
    from PySide6.QtCore import QCoreApplication
    from sentinal.application import prepare_runtime
    from sentinal.config import AppConfig
    from sentinal.core.v02_settings import V02Settings
    from sentinal.core.incidents import TemporalEventEngine,TemporalRule
    from sentinal.storage.camera_registry import CameraRegistry
    from sentinal.vision.multi_camera import MultiCameraWorker
    from tools.verify_rtsp_v02 import LocalRTSP
    app=QCoreApplication.instance() or QCoreApplication([])
    evidence=ROOT/'docs/evidence/v021-2026-11-02';evidence.mkdir(parents=True,exist_ok=True)
    report={'test':'Actual simultaneous loopback H264 RTSP cameras with one shared model set',
        'created_utc':datetime.now(timezone.utc).isoformat(),'physical_cameras_tested':False,
        'fixtures':['data/v02-demo/handgun_repeated_still.mp4','data/v02-demo/fire_repeated_still.mp4'],
        'fixture_scope':'Real licensed photos repeated as videos; genuine model inference, not natural-motion accuracy proof',
        'mock_inference':False,'images_saved':False,'checks':{},'packets':[],'states':[],'errors':[],'incidents':[],'passed':False}
    worker=registry=feed_a=feed_b=None;last={};counts={};first_sessions={};started=time.monotonic()
    engine=TemporalEventEngine(TemporalRule(confidence_threshold=.25,min_consecutive=3,persistence_s=.4,max_gap_s=2.,cooldown_s=10.))
    def consume(packet,ident):
        report['incidents'].extend(event.to_dict() for event in engine.process(ident,packet.session_id,packet.hazards,packet.timestamp,packet.source_time_s))
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    def poll(predicate,timeout=35):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            app.processEvents()
            if worker:
                for ident,packet in worker.take_latest().items():
                    last[ident]=packet;counts[ident]=counts.get(ident,0)+1;first_sessions.setdefault(ident,packet.session_id)
                    if len(report['packets'])<300:
                        report['packets'].append({'camera_id':ident,'session_id':packet.session_id,'frame':packet.frame_index,
                            'processing_fps':packet.fps,'inference_ms':packet.inference_ms,'frame_age_ms':packet.frame_age_ms,
                            'dropped_frames':packet.dropped_frames,'diagnostics':packet.diagnostics,
                            'hazards':[{'category':h.category,'confidence':h.confidence,'track_id':h.track_id,'model_id':h.model_id,'model_version':h.model_version} for h in packet.hazards],
                            'model_health':packet.detector_health})
            if predicate():return
            time.sleep(.005)
        raise AssertionError('Timed out waiting for simultaneous-stream inference or recovery')
    try:
        prepare_runtime()
        with tempfile.TemporaryDirectory(dir=ROOT/'work/tmp',prefix='multi-rtsp-') as directory:
            work=Path(directory)
            registry=CameraRegistry(work/'camera-registry/registry.sqlite3')
            feed_a=LocalRTSP(work/'a',ROOT/'data/v02-demo/handgun_repeated_still.mp4').start()
            feed_b=LocalRTSP(work/'b',ROOT/'data/v02-demo/fire_repeated_still.mp4').start()
            a=registry.upsert_network('Public handgun fixture',feed_a.url)
            b=registry.upsert_network('Public fire fixture',feed_b.url)
            worker=MultiCameraWorker(AppConfig())
            worker.state_changed.connect(lambda ident,state,message:report['states'].append({'camera_id':ident,'state':state,'message':message,'elapsed_s':time.monotonic()-started}))
            worker.error.connect(lambda ident,message:report['errors'].append({'camera_id':ident,'message':message}))
            worker.set_options(hazards_enabled=True,hazard_settings=replace(V02Settings(),sample_interval_s=.2))
            worker.set_incident_consumer(consume);worker.start()
            check('no_capture_before_request',not worker.is_monitoring and worker.detector is None)
            worker.request_start((registry.resolve(a.camera_id),registry.resolve(b.camera_id)))
            poll(lambda:counts.get(a.camera_id,0)>=8 and counts.get(b.camera_id,0)>=8)
            check('both_simultaneous_sources_process_real_frames',set(last)=={a.camera_id,b.camera_id})
            check('independent_initial_sessions',last[a.camera_id].session_id!=last[b.camera_id].session_id)
            check('one_shared_ordinary_model',worker.detector.model is not None)
            models=(id(worker.detector.model),*(id(worker.hazard_suite._models[key]['model']) for key in ('weapons','fire_smoke')))
            check('both_specialized_models_actually_active',all(last[ident].detector_health[key]['status']=='active' for ident in last for key in ('weapons','fire_smoke')))
            poll(lambda:any(row['camera_id']==a.camera_id and any(h['category']=='weapon_handgun' for h in row['hazards']) for row in report['packets']) and any(row['camera_id']==b.camera_id and any(h['category']=='fire' for h in row['hazards']) for row in report['packets']))
            check('real_weapon_and_fire_outputs_in_distinct_streams',True)
            poll(lambda:any(event['source_id']==a.camera_id and event['category']=='weapon_handgun' and event['status']=='ALERTED' for event in report['incidents']) and any(event['source_id']==b.camera_id and event['category']=='fire' and event['status']=='ALERTED' for event in report['incidents']))
            check('real_outputs_reach_per_camera_temporal_alerts',True)
            b_session=last[b.camera_id].session_id;b_count=counts[b.camera_id]
            feed_a.interrupt()
            poll(lambda:any(row['camera_id']==a.camera_id and row['state']=='reconnecting' for row in report['states']))
            poll(lambda:counts[b.camera_id]>=b_count+8)
            check('uninterrupted_camera_continues_during_other_outage',last[b.camera_id].session_id==b_session)
            feed_a.start_publisher()
            poll(lambda:last[a.camera_id].session_id!=first_sessions[a.camera_id])
            check('recovered_source_has_fresh_session',True)
            check('unaffected_source_session_preserved',last[b.camera_id].session_id==b_session)
            check('same_model_objects_reused_after_reconnect',models==(id(worker.detector.model),*(id(worker.hazard_suite._models[key]['model']) for key in ('weapons','fire_smoke'))))
            b_count=counts[b.camera_id];worker.request_stop(a.camera_id)
            poll(lambda:a.camera_id not in worker.source_ids and counts[b.camera_id]>=b_count+4)
            check('individual_stop_keeps_other_stream_running',b.camera_id in worker.source_ids)
            stop_started=time.monotonic();worker.request_stop();poll(lambda:not worker.is_monitoring)
            report['stop_all_ms']=(time.monotonic()-stop_started)*1000
            check('all_source_resources_released',not worker.source_ids and not worker._retiring)
            worker.request_shutdown();poll(lambda:not worker.isRunning())
            check('worker_shutdown',True)
            report['frames_per_camera']=counts;report['passed']=all(report['checks'].values())
    except Exception as exc:
        report['failure']=str(exc)
        import traceback
        report['traceback']=traceback.format_exc()
    finally:
        if worker is not None:
            worker.request_shutdown();worker.wait(15000)
        if feed_a is not None:feed_a.close()
        if feed_b is not None:feed_b.close()
        if registry is not None:registry.close()
        report['elapsed_s']=time.monotonic()-started
        (evidence/args.report_name).write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k not in {'packets','states','incidents'}},indent=2))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
