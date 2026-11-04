"""Bounded real-model repeated-file throughput/resource check; no camera/evidence."""
from pathlib import Path
import argparse,json,sys,time,statistics
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sentinal.config import AppConfig
from sentinal.vision.pipeline import VisionPipeline
from sentinal.vision.video_source import SourceSpec
import psutil


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cycles',type=int,default=20)
    args=parser.parse_args()
    if not 2<=args.cycles<=40:raise ValueError('Use2–40boundedcycles')
    pipe=VisionPipeline(AppConfig(image_size=480));pipe.configure_hazards(enabled=('weapons','fire_smoke'),confidence=.35,image_size=480,sample_interval_s=.2)
    process=psutil.Process();rows=[];sessions=set();identities=None;started=time.monotonic();frames=0;hazard_frames=0
    report={'test':'Real local repeated-file inference/resource observation; not field tracking accuracy','cycles':rows,'passed':False}
    try:
        for cycle in range(args.cycles):
            pipe.start(SourceSpec('file',str(ROOT/'data/v02-demo/handgun_repeated_still.mp4')))
            assert pipe.session_id not in sessions;sessions.add(pipe.session_id)
            count=0;latencies=[];sample_times=[];cycle_start=time.monotonic()
            while True:
                packet=pipe.step()
                if packet is None:break
                count+=1;frames+=1;latencies.append(packet.inference_ms)
                if packet.hazard_sampled:
                    hazard_frames+=1;sample_times.append(packet.diagnostics['hazard_inference_ms'])
            models=(id(pipe.detector.model),*(id(pipe.hazard_suite._models[key]['model']) for key in ('weapons','fire_smoke')))
            if identities is None:identities=models
            assert models==identities,'Loaded model unexpectedly replaced between sessions'
            pipe.stop();assert pipe.source is None
            rows.append({'cycle':cycle,'frames':count,'elapsed_s':time.monotonic()-cycle_start,'mean_total_inference_ms':statistics.mean(latencies),'mean_hazard_sample_ms':statistics.mean(sample_times),'parent_rss_mb':process.memory_info().rss/1024**2})
            print(json.dumps(rows[-1]),flush=True)
        report.update(elapsed_s=time.monotonic()-started,frames=frames,specialized_samples=hazard_frames,unique_sessions=len(sessions),models_reused=True,source_released=pipe.source is None)
        report['warm_rss_span_mb']=max(r['parent_rss_mb'] for r in rows[2:])-min(r['parent_rss_mb'] for r in rows[2:]) if len(rows)>2 else None
        report['passed']=len(rows)==args.cycles
    except Exception as exc:report['failure']=str(exc)
    finally:
        pipe.stop()
        if pipe.hazard_suite:pipe.hazard_suite.close()
        output=ROOT/'docs/evidence/v02-2026-11-01/soak.json';output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
