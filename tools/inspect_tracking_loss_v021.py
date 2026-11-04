"""Actual old track-output versus raw-predict observations on licensed inputs."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import cv2
from sentinal.vision.specialized import SpecializedSuite,observations_from_result
from sentinal.vision.model_registry import ASSETS
suite=SpecializedSuite(device='mps',enabled=('weapons','fire_smoke'),confidence=.25,image_size=640)
rows=[]
for key,photo in [('weapons','knife.jpg'),('fire_smoke','fire.jpg'),('fire_smoke','smoke.jpg')]:
    state=suite._load(key);model=state['model']
    frames=[cv2.imread(str(ROOT/'data/v02-evaluation/bright_light.jpg')),cv2.imread(str(ROOT/'data/v02-evaluation'/photo))]
    from sentinal.vision.tracker import reset_model_trackers
    reset_model_trackers(model)
    for index,frame in enumerate(frames):
        kwargs=dict(source=frame,classes=state['classes'],conf=.05,iou=.6,imgsz=640,device='mps',verbose=False,save=False,stream=False)
        raw=model.predict(**kwargs,mode='predict')[0]
        predicted=observations_from_result(raw,frame.shape,ASSETS[key],.25)
        tracked=model.track(**kwargs,persist=True,tracker='bytetrack.yaml')[0]
        retained=observations_from_result(tracked,frame.shape,ASSETS[key],.25)
        rows.append({'module':key,'step':index,'fixture':'bright_light.jpg' if index==0 else photo,'raw':[{'category':o.category,'confidence':o.confidence,'bbox':o.bbox} for o in predicted],'legacy_tracked':[{'category':o.category,'confidence':o.confidence,'bbox':o.bbox} for o in retained]})
suite.close()
output=ROOT/'docs/evidence/v021-2026-11-02/raw-vs-legacy-tracking.json';output.write_text(json.dumps({'scope':'Real trained models on licensed photos, background then new object. Shows tracker confirmation loss, not field accuracy.','rows':rows},indent=2))
print(json.dumps(rows,indent=2))
