"""Real inference on licensed reported-item photos; no predictions are seeded."""
from pathlib import Path
from dataclasses import asdict
import json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2
from sentinal.config import ROOT,AppConfig
from sentinal.vision.detector import YOLODetector
from sentinal.vision.specialized import SpecializedSuite
DATA=ROOT/'data/v021-items';OUT=ROOT/'docs/evidence/v021-2026-11-02'
TARGETS={'scissors_household':'scissors','scissors_pair':'scissors','spoon_small':'spoon','spoon_chopsticks':'spoon','cleaver':'knife','utility_blade':'knife','toy_gun':None}

def main():
    rows=[]
    for path in ('models/yolo11n.pt','models/yolov8n-oiv7.pt','models/yolov8s-oiv7.pt'):
        detector=YOLODetector(AppConfig(model_path=path,device='mps',image_size=640,confidence=.25))
        for name,target in TARGETS.items():
            frame=cv2.imread(str(DATA/(name+'.jpg')));detector.reset_tracking();objects=detector.infer(frame,.05,source_id=name)
            row={'module':'ordinary','model':path,'fixture':name,'expected_category':target,'objects':[asdict(o) for o in objects],'latency_ms':detector.last_inference_ms}
            rows.append(row);print(path,name,[(o.label,round(o.confidence,3)) for o in objects if o.confidence>=.25],flush=True)
        del detector
    suite=SpecializedSuite(device='mps',enabled=('weapons','fire_smoke'),confidence=.05,image_size=640)
    for name,target in TARGETS.items():
        frame=cv2.imread(str(DATA/(name+'.jpg')));suite.reset_tracking();objects=suite.infer(frame,source_id=name)
        rows.append({'module':'specialized','fixture':name,'expected_category':target,'objects':[asdict(o) for o in objects],'health':{k:dict(v) for k,v in suite.health.items()}})
        print('specialized',name,[(o.category,round(o.confidence,3)) for o in objects if o.confidence>=.25],flush=True)
    suite.close();OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'reported-items-screening.json').write_text(json.dumps({'scope':'Seven selected licensed photos of user-reported categories; one toy known from provenance, no toy/real discrimination claimed. Threshold .05 raw outputs retained; summaries use .25. Not representative field validation.','rows':rows},indent=2)+'\n')
if __name__=='__main__':main()
