"""Explicit headless camera/video -> real inference -> signed incident sender.

Invoke this command to start monitoring; importing the module never captures.
Preview transport is an extra explicit loopback-only RAM feature, off by default.
"""
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time
from .edge import EdgeConfig, EdgePublisher
from .outbox import local_file
from sentinal.config import ROOT, AppConfig
from sentinal.core.incidents import TemporalEventEngine,TemporalRule
from sentinal.vision.pipeline import VisionPipeline
from sentinal.vision.video_source import SourceSpec,VideoSourceError


def parser():
    args=argparse.ArgumentParser(description=__doc__)
    args.add_argument('--config',default='config/connected/edge-credentials.json')
    source=args.add_mutually_exclusive_group(required=True)
    source.add_argument('--video')
    source.add_argument('--stream-url-file',help='Owner-only project file containing an authorized RTSP/HTTP URL; never put passwords on the command line')
    source.add_argument('--camera-device-id',help='Explicit exact device identity from the existing desktop camera list')
    args.add_argument('--camera-id',help='Stable logical camera ID; generated from device/source if omitted')
    args.add_argument('--name',default='Authorized source')
    args.add_argument('--device',choices=('auto','cpu','mps'),default='auto')
    args.add_argument('--detectors',choices=('both','weapons','fire_smoke'),default='both')
    args.add_argument('--image-size',type=int,choices=(320,480,640,960),default=640)
    args.add_argument('--display-confidence',type=float,default=.25)
    args.add_argument('--alert-confidence',type=float,default=.6)
    args.add_argument('--persistence',type=float,default=1.)
    args.add_argument('--consecutive',type=int,default=3)
    args.add_argument('--max-gap',type=float,default=.75)
    args.add_argument('--sample-interval',type=float,default=.2)
    args.add_argument('--preview',action='store_true',help='Explicitly send annotated frames only to a loopback backend with preview enabled, in RAM; no evidence recording')
    args.add_argument('--preview-rate',type=float,default=2.)
    args.add_argument('--max-seconds',type=float,default=0)
    args.add_argument('--unpaced',action='store_true',help='Process files without real-time pacing; benchmark/demo scope must identify this')
    args.add_argument('--loop',action='store_true',help='Replay local video with a fresh session; existing weights remain loaded')
    args.add_argument('--report',help='Optional project-local metadata report, without images or source URLs')
    return args


def source_spec(args):
    if args.video:
        value=Path(args.video).expanduser().resolve()
        if not value.is_file():raise ValueError('Selected video is unavailable')
        return SourceSpec('file',str(value))
    if args.stream_url_file:
        path=local_file(args.stream_url_file)
        if path.stat().st_mode&0o077 or path.stat().st_size>8192:
            raise ValueError('Stream credentials require a bounded owner-only project file')
        return SourceSpec('stream',path.read_text().strip())
    if not args.camera_device_id:
        raise ValueError('Choose an exact camera; no implicit camera will open')
    return SourceSpec('camera',0,camera_device_id=args.camera_device_id,camera_name='Explicit selected camera')


def model_metadata(health,processing=True):
    result=[]
    for value in health.values():
        if not value.get('model_id') or not value.get('model_version'):continue
        result.append({'model_id':value['model_id'],'version':value['model_version'],
            'classes':list(value.get('classes',())),
            'status':'idle' if not processing and value.get('status')=='active' else value.get('status','unavailable'),'device':value.get('device','unavailable')})
    return result


def heartbeat_payload(state,camera_id,name,packet,times,model_health):
    """Inactive sources retain provenance without advertising current throughput."""
    health={'status':state}
    if packet is not None and state=='running':
        health['processing_fps']=(len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0.
        health['inference_ms']=packet.inference_ms
        if packet.diagnostics.get('memory_rss_mb') is not None:health['memory_rss_mb']=packet.diagnostics['memory_rss_mb']
    camera={'camera_id':camera_id,'name':name,'status':'running' if state=='running' else 'reconnecting' if state=='reconnecting' else 'error' if state=='error' else 'stopped'}
    if packet is not None:camera['last_frame_at']=packet.timestamp
    return health,[camera],model_metadata(model_health or {},processing=state=='running')


def run(args,on_packet=None):
    config=EdgeConfig.load(args.config)
    spec=source_spec(args)
    if args.loop and spec.kind!='file':raise ValueError('Only local files can loop')
    if not 0<=args.max_seconds<=86400 or not .05<=args.sample_interval<=10:
        raise ValueError('Invalid monitoring duration or sample interval')
    if not .05<=args.display_confidence<=.99:raise ValueError('Invalid box display score')
    rule=TemporalRule(confidence_threshold=args.alert_confidence,min_consecutive=args.consecutive,
        persistence_s=args.persistence,max_gap_s=args.max_gap)
    camera_id=args.camera_id or 'cam-'+hashlib.sha256((config.device_id+':'+spec.kind+':'+str(spec.camera_key if spec.kind=='camera' else spec.value)).encode()).hexdigest()[:20]
    if not camera_id or len(camera_id)>128 or '://' in camera_id or '@' in camera_id:
        raise ValueError('Choose a stable camera identifier without an address')
    pipeline=VisionPipeline(AppConfig(device=args.device,image_size=args.image_size))
    enabled=('weapons','fire_smoke') if args.detectors=='both' else (args.detectors,)
    pipeline.configure_hazards(enabled=enabled,confidence=args.display_confidence,
        image_size=args.image_size,sample_interval_s=args.sample_interval)
    engine=TemporalEventEngine(rule)
    publisher=EdgePublisher(config);preview=None
    if args.preview:
        from .preview import PreviewPublisher
        preview=PreviewPublisher(config,args.preview_rate)
    report={'source_kind':spec.kind,'camera_id':camera_id,'source_urls_saved':False,
        'inference_mocked':False,'frames_processed':0,'hazard_samples':0,'candidate_count':0,
        'alert_count':0,'alerts':[],'preview_explicit':bool(args.preview),'video_saved':False,
        'real_time_file_pacing':spec.kind=='file' and not args.unpaced,'alert_report_cap':500,'passed':False}
    times=deque(maxlen=60);latency_total=0.;last_health=None;last_heartbeat=0.;retries=0
    start=time.monotonic();playback_start=start;last_packet=None;terminal='stopped'
    def heartbeat(state,packet=None):
        nonlocal last_heartbeat
        publisher.submit_heartbeat(*heartbeat_payload(state,camera_id,args.name,packet,times,last_health))
        last_heartbeat=time.monotonic()
    def open_source():
        attempts=0
        while True:
            try:
                pipeline.start(spec)
                return
            except VideoSourceError:
                pipeline.stop()
                if spec.kind!='stream' or attempts>=pipeline.config.stream_reconnect_attempts:raise
                attempts+=1;heartbeat('reconnecting');time.sleep(min(10,2**(attempts-1)))
    try:
        publisher.start()
        if preview is not None:preview.start()
        open_source();playback_start=time.monotonic()
        while not args.max_seconds or time.monotonic()-start<args.max_seconds:
            try:packet=pipeline.step(category_filter='all')
            except VideoSourceError:
                pipeline.stop()
                if spec.kind!='stream' or retries>=pipeline.config.stream_reconnect_attempts:
                    terminal='error';raise
                retries+=1;heartbeat('reconnecting');time.sleep(min(10,2**(retries-1)))
                open_source();engine.reset(camera_id);continue
            if packet is None:
                if args.loop:
                    pipeline.start(spec);engine.reset(camera_id);times.clear();playback_start=time.monotonic();continue
                break
            if spec.kind=='file' and not args.unpaced:
                delay=packet.source_time_s-(time.monotonic()-playback_start)
                if delay>0:time.sleep(min(delay,1))
            retries=0
            last_packet=packet;times.append(time.monotonic());latency_total+=packet.inference_ms
            report['frames_processed']+=1
            if packet.hazard_sampled:
                report['hazard_samples']+=1;last_health=packet.detector_health
                for event in engine.process(camera_id,packet.session_id,packet.hazards,packet.timestamp,packet.source_time_s):
                    if event.status=='CANDIDATE':report['candidate_count']+=1
                    if event.status=='ALERTED':
                        report['alert_count']+=1;report['alerts'].append(event.to_dict())
                        if len(report['alerts'])>500:report['alerts'].pop(0)
                        if not publisher.submit_incident(event.to_dict()):raise RuntimeError('Incident was not queued')
                if preview is not None:preview.submit(packet,camera_id)
            if time.monotonic()-last_heartbeat>=2 or last_heartbeat==0:heartbeat('running',packet)
            if on_packet is not None:on_packet(packet,report)
    except KeyboardInterrupt:
        report['interrupted_by_user']=True
    except Exception:
        terminal='error';report['error']='Monitoring stopped. Check local diagnostics, source availability and connected settings.'
    finally:
        pipeline.stop()
        if pipeline.hazard_suite is not None:pipeline.hazard_suite.close()
        if publisher.is_alive():
            heartbeat('error' if terminal=='error' else 'idle',last_packet)
            # Give already accepted metadata a bounded chance to reach the backend.
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and publisher.is_alive():
                state=publisher.status()
                if state['queued']==0 and state['delivered']>=state['submitted']:break
                time.sleep(.02)
        if preview is not None:
            report['preview_released']=preview.close();report['preview_frames_sent']=preview.sent
            report['preview_frames_dropped']=preview.dropped;report['preview_error']=preview.last_error
        report['edge_released']=publisher.close()
        report['delivery']=publisher.status();report['source_released']=pipeline.source is None
        report['elapsed_s']=time.monotonic()-start
        report['mean_inference_ms']=latency_total/report['frames_processed'] if report['frames_processed'] else None
        report['observed_processing_fps']=report['frames_processed']/report['elapsed_s']
        report['model_health']=last_health or {}
        report['passed']=bool(report['frames_processed']) and not report.get('error') and report['edge_released'] and report['source_released'] and report['delivery']['failed']==0 and report['delivery']['queued']==0
        if args.report:
            path=local_file(args.report);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(report,indent=2)+'\n');path.chmod(0o600)
    return report


def main(argv=None):
    args=parser().parse_args(argv)
    try:report=run(args)
    except (ValueError,OSError):
        print('SENTINAL could not start: check the selected source, owner-only credentials and explicit connection preferences.')
        return 2
    print(json.dumps({key:value for key,value in report.items() if key not in {'alerts','model_health'}},indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
