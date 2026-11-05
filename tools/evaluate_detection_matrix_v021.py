"""Bounded real-model combinations; derived conditions are never independent data."""
from pathlib import Path
from dataclasses import asdict
from collections import defaultdict
import argparse,json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cv2,numpy as np
from sentinal.config import ROOT,AppConfig
from sentinal.vision.detector import YOLODetector
from sentinal.vision.specialized import SpecializedSuite
from tools.evaluate_v02_models import iou
OUT=ROOT/'docs/evidence/v021-2026-11-02'
SIZES=(320,640,960);THRESHOLDS=(.15,.25,.35,.5,.6)
CONDITIONS=('original','dim_35percent','blur_sigma4','central_cover20percent','small_30percent')
BASE_MODELS=('models/yolo11n.pt','models/yolov8n-oiv7.pt','models/yolov8s-oiv7.pt','models/yolo11s.pt')


def scene_records():
    old=json.loads((ROOT/'data/v02-evaluation/labels.json').read_text())['scenes']
    new=json.loads((ROOT/'data/v021-items/labels.json').read_text())['scenes']
    records=[]
    for row in old:
        records.append({'source':str(Path('data/v02-evaluation')/row['file']),'hazards':row['boxes'],'ordinary':[{'category':'knife','bbox':x['bbox']} for x in row['boxes'] if x['category']=='weapon_knife'],'new_reported_item':False,'already_derived':row['derived']})
    for row in new:records.append({'source':str(Path('data/v021-items')/row['file']),'hazards':row['hazards'],'ordinary':row['ordinary'],'new_reported_item':True,'already_derived':False,'known_toy_lookalike':bool(row.get('lookalike_targets'))})
    return records


def condition(frame,labels,name):
    boxes=[dict(row,bbox=list(row['bbox'])) for row in labels]
    if name=='original':return frame,boxes
    if name=='dim_35percent':return np.rint(frame.astype(np.float32)*.35).astype(np.uint8),boxes
    if name=='blur_sigma4':return cv2.GaussianBlur(frame,(11,11),4),boxes
    h,w=frame.shape[:2]
    if name=='central_cover20percent':
        image=frame.copy();image[:,int(w*.4):int(w*.6)]=114;return image,boxes
    scale=.3;rw=max(1,round(w*scale));rh=max(1,round(h*scale));x=(w-rw)//2;y=(h-rh)//2
    image=np.full_like(frame,114);image[y:y+rh,x:x+rw]=cv2.resize(frame,(rw,rh))
    for row in boxes:
        a,b,c,d=row['bbox'];row['bbox']=[a*rw/w+x,b*rh/h+y,c*rw/w+x,d*rh/h+y]
    return image,boxes


def score(rows,threshold,categories):
    output={}
    for category in categories:
        tp=fp=fn=stp=sfp=sfn=0
        for row in rows:
            predictions=[x for x in row['objects'] if x['category']==category and x['confidence']>=threshold]
            labels=[x for x in row['labels'] if x['category']==category]
            stp+=bool(predictions) and bool(labels);sfp+=bool(predictions) and not labels;sfn+=bool(labels) and not predictions
            assigned=set()
            for prediction in sorted(predictions,key=lambda x:x['confidence'],reverse=True):
                matches=[(iou(prediction['bbox'],label['bbox']),index) for index,label in enumerate(labels) if index not in assigned]
                overlap,index=max(matches,default=(0,-1))
                if overlap>=.5:tp+=1;assigned.add(index)
                else:fp+=1
            fn+=len(labels)-len(assigned)
        output[category]={'objects_iou50':{'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None},'scene_presence':{'tp':stp,'fp':sfp,'fn':sfn,'precision':stp/(stp+sfp) if stp+sfp else None,'recall':stp/(stp+sfn) if stp+sfn else None}}
    return output


def main():
    records=scene_records();rows=[];started=time.perf_counter()
    # Both specialized models share weights across all sources/resolutions;
    # association resets ensure this is static detector evaluation, not tracking.
    suite=SpecializedSuite(device='mps',enabled=('weapons','fire_smoke'),confidence=.05)
    for size in SIZES:
        suite.configure(image_size=size)
        for transform in CONDITIONS:
            for record in records:
                frame=cv2.imread(str(ROOT/record['source']));image,labels=condition(frame,record['hazards'],transform)
                suite.reset_tracking();objects=suite.infer(image,source_id=record['source']);rows.append({'group':'specialized','model':'selected-weapons+fire_smoke','size':size,'condition':transform,'source':record['source'],'labels':labels,'known_toy_lookalike':record.get('known_toy_lookalike',False),'objects':[asdict(o) for o in objects]})
            print('specialized',size,transform,flush=True)
    suite.close()
    for model in BASE_MODELS:
        detector=YOLODetector(AppConfig(model_path=model,device='mps',confidence=.05))
        for size in SIZES:
            detector.config=AppConfig(model_path=model,device='mps',confidence=.05,image_size=size)
            for transform in CONDITIONS:
                for record in (x for x in records if x['new_reported_item']):
                    frame=cv2.imread(str(ROOT/record['source']));image,labels=condition(frame,record['ordinary'],transform)
                    detector.reset_tracking();objects=detector.infer(image,.05,source_id=record['source'])
                    rows.append({'group':'ordinary','model':model,'size':size,'condition':transform,'source':record['source'],'labels':labels,'objects':[{'category':o.label,'confidence':o.confidence,'bbox':o.bbox,'track_id':o.track_id} for o in objects]})
                print(model,size,transform,flush=True)
        del detector
    groups=defaultdict(list)
    for row in rows:groups[(row['group'],row['model'],row['size'],row['condition'])].append(row)
    summary=[]
    for (group,model,size,transform),values in groups.items():
        categories=('weapon_handgun','weapon_firearm','weapon_longgun','weapon_knife','fire','smoke') if group=='specialized' else ('spoon','scissors','knife')
        for threshold in THRESHOLDS:summary.append({'group':group,'model':model,'size':size,'condition':transform,'threshold':threshold,'scenes':len(values),'metrics':score(values,threshold,categories)})
    report={'scope':'Selected24source photos/scenes (17previouscalibration+7newreporteditems), artificial dim/blur/occlusion/scale variants; no representative or independent-field accuracy claim. Original fire/smoke boxes are coarse regions; cover boxes remain amodal. Toy gun is a negative for genuinefirearm and separately flagged, never a realweaponTP. Looseblades have no independent trainedcategory.','sizes':SIZES,'thresholds':THRESHOLDS,'conditions':CONDITIONS,'actual_inference_groups':len(rows),'actual_model_forward_passes':sum(2 if row['group']=='specialized' else 1 for row in rows),'thresholded_frame_model_combinations':len(rows)*len(THRESHOLDS),'elapsed_s':time.perf_counter()-started,'rows':rows,'summaries':summary}
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'detection-combination-matrix.json').write_text(json.dumps(report,indent=2)+'\n')
    print('COMPLETE',len(rows),'inferencegroups',len(summary),'summaryconfigurations',report['elapsed_s'],flush=True)
if __name__=='__main__':main()
