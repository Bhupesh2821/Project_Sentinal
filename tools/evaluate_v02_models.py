"""Real local model evaluation; never manufactures detector outputs."""
import argparse,json,time,platform,importlib.util
from dataclasses import asdict
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2,numpy as np,psutil,torch
from sentinal.config import ROOT
from sentinal.vision.specialized import SpecializedSuite
from sentinal.vision.model_registry import ASSETS
DATA=ROOT/'data/v02-evaluation'
OUTPUT=ROOT/'docs/evidence/v02-2026-11-01'


def iou(a,b):
    width=max(0,min(a[2],b[2])-max(a[0],b[0]));height=max(0,min(a[3],b[3])-max(a[1],b[1]))
    intersection=width*height
    return intersection/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection) if intersection else 0.


def metrics(rows,threshold):
    categories=('weapon_handgun','weapon_longgun','weapon_knife','weapon_firearm','fire','smoke')
    output={}
    for category in categories:
        tp=fp=fn=scene_tp=scene_fp=scene_fn=0
        for row in rows:
            predictions=[p for p in row['observations'] if p['category']==category and p['confidence']>=threshold]
            labels=[p for p in row['labels'] if p['category']==category]
            scene_tp+=bool(predictions) and bool(labels);scene_fp+=bool(predictions) and not labels;scene_fn+=bool(labels) and not predictions
            matched=set()
            for prediction in sorted(predictions,key=lambda p:p['confidence'],reverse=True):
                matches=[(iou(prediction['bbox'],label['bbox']),index) for index,label in enumerate(labels) if index not in matched]
                best=max(matches,default=(0,-1))
                if best[0]>=.5:tp+=1;matched.add(best[1])
                else:fp+=1
            fn+=len(labels)-len(matched)
        output[category]={'objects_iou50':{'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None},'scene_presence':{'tp':scene_tp,'fp':scene_fp,'fn':scene_fn,'precision':scene_tp/(scene_tp+scene_fp) if scene_tp+scene_fp else None,'recall':scene_tp/(scene_tp+scene_fn) if scene_tp+scene_fn else None}}
    return output


def evaluate(image_size=640):
    annotations=json.loads((DATA/'labels.json').read_text())
    suite=SpecializedSuite(device='mps',enabled=('weapons','fire_smoke'),confidence=.35,image_size=image_size)
    rows=[]
    for scene in annotations['scenes']:
        frame=cv2.imread(str(DATA/scene['file']));suite.reset_tracking();started=time.perf_counter()
        observations=suite.infer(frame)
        row={'file':scene['file'],'derived':scene['derived'],'labels':scene['boxes'],'observations':[asdict(o) for o in observations],'elapsed_ms':(time.perf_counter()-started)*1000,'health':dict(suite.health)};rows.append(row)
        print(scene['file'],[(o.category,round(o.confidence,3)) for o in observations],flush=True)
    suite.close()
    result={'input_size':image_size,'scope':annotations['scope'],'unique_natural_photos':14,'derived_scenes':3,'scenes':17,'confidence_thresholds':[.35,.6],'model_versions':{k:asdict(a) for k,a in ASSETS.items()},'results':rows,'metrics':{str(t):metrics(rows,t) for t in (.35,.6)}}
    OUTPUT.mkdir(parents=True,exist_ok=True);(OUTPUT/('model-evaluation.json' if image_size==640 else 'model-evaluation-'+str(image_size)+'.json')).write_text(json.dumps(result,indent=2))


def benchmark():
    frame=cv2.imread(str(DATA/'handgun.jpg'));process=psutil.Process();results=[]
    devices=['cpu']+(['mps'] if torch.backends.mps.is_available() else [])
    for device in devices:
        suite=SpecializedSuite(device=device,enabled=('weapons','fire_smoke'),confidence=.35,image_size=640)
        for size in (320,480,640):
            suite.configure(image_size=size);started=time.perf_counter();suite.infer(frame);cold=(time.perf_counter()-started)*1000
            times=[]
            for index in range(12):
                started=time.perf_counter();suite.infer(frame,frame_index=index,source_time_s=index/10);times.append((time.perf_counter()-started)*1000)
            row={'device':device,'input_size':size,'source_pixels':[frame.shape[1],frame.shape[0]],'samples':len(times),'first_call_ms':cold,'warm_mean_ms':float(np.mean(times)),'warm_p95_ms':float(np.percentile(times,95)),'measured_inference_throughput_fps':1000/float(np.mean(times)),'process_rss_mb':process.memory_info().rss/1024**2,'health':dict(suite.health)}
            if device=='mps':row['mps_tensor_allocated_mb']=torch.mps.current_allocated_memory()/1024**2;row['mps_driver_allocated_mb']=torch.mps.driver_allocated_memory()/1024**2
            results.append(row);print('benchmark',device,size,round(row['warm_mean_ms'],2),'ms',flush=True)
        suite.close()
        if device=='mps':torch.mps.empty_cache()
    OUTPUT.mkdir(parents=True,exist_ok=True);(OUTPUT/'model-benchmark.json').write_text(json.dumps({'scope':'Both specialized detector models plus ByteTrack on one real handgun photo. Twelve warm calls per configuration. Throughput excludes camera decoding, base YOLO11n and UI; not end-to-end FPS. Concurrent project verification may affect timings. Models retained between sizes. First call per size includes shape warmup; only first per backend also loads weights.','hardware':platform.platform(),'torch':torch.__version__,'ram_gb':psutil.virtual_memory().total/1024**3,'onnxruntime_installed':importlib.util.find_spec('onnxruntime') is not None,'coremltools_installed':importlib.util.find_spec('coremltools') is not None,'results':results},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--benchmark',action='store_true');parser.add_argument('--size',type=int,choices=(320,480,640),default=640);args=parser.parse_args()
    benchmark() if args.benchmark else evaluate(args.size)
