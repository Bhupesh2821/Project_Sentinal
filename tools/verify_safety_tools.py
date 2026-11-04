#!/usr/bin/env python3
"""Real local OpenImages model verification, with Python network calls denied.

Selected close-up public fixtures establish executed detections, never a
calibrated accuracy rate or protective-equipment compliance assessment.
"""
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import socket
import statistics
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sentinal.config import AppConfig
from sentinal.vision.detector import YOLODetector
from sentinal.vision.object_catalog import allowed_class_ids, canonical_label


def iou(a, b):
    inter = max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1]))
    area = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / area if area > 0 else 0.


def main():
    import cv2
    import torch
    from ultralytics import YOLO
    from ultralytics.trackers import register_tracker
    target = ROOT / 'docs/evidence/camera-cctv-catalog-2026-10-28/safety-tools.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    selection = json.loads((ROOT / 'work/openimages-safety/selected.json').read_text())
    fixtures = [entry for entries in selection.values() for entry in entries]
    weights = ROOT / 'models/yolov8n-oiv7.pt'
    attempts = []
    def denied(*args, **kwargs):
        attempts.append('Python network operation blocked')
        raise RuntimeError('Verification denies Python network connections')
    report = {'test':'Real expanded-model inference on selected public images and recorded video',
              'model':weights.name, 'sha256':sha256(weights.read_bytes()).hexdigest(),
              'confidence_threshold':.25, 'inference_size':640,
              'fixture_selection':'Prior selection of large/visible annotated objects; this is not an unbiased accuracy sample',
              'limitations':'Generic helmet/glove/boot recognition does not establish protective rating, correct use or compliance. Repeated stills are not moving-object tracking proof. Network denial covers Python socket entry points, not an OS packet capture.',
              'camera_opened':False, 'camera_images_saved':False, 'backends':[], 'network_attempts':attempts, 'passed':False}
    try:
        with patch.object(socket.socket,'connect',denied), patch.object(socket,'create_connection',denied), patch.object(socket,'getaddrinfo',denied):
            for preference in ['cpu','mps']:
                if preference == 'mps' and not torch.backends.mps.is_available():
                    report['backends'].append({'requested':'mps','blocked':'MPS is unavailable'})
                    continue
                detector = YOLODetector(AppConfig(model_path='models/yolov8n-oiv7.pt',device=preference))
                detector.load()
                backend = {'requested':preference, 'actual':detector.device, 'raw_class_count':len(detector.model.names),
                           'permitted_class_count':len(allowed_class_ids(detector.model.names)), 'examples':[], 'warm_inference_ms':[]}
                report['backends'].append(backend)
                for entry in fixtures:
                    path = ROOT / 'work/openimages-safety' / (entry['image_id'] + '.jpg')
                    frame = cv2.imread(str(path))
                    if frame is None:
                        raise RuntimeError('A selected real fixture cannot be decoded')
                    height,width = frame.shape[:2]
                    x1,y1,x2,y2=entry['bbox']
                    truth=(x1*width,y1*height,x2*width,y2*height)
                    detector.reset_tracking()
                    all_rounds=[]
                    for repeat in range(3):
                        output=detector.infer(frame)
                        all_rounds.append(output)
                        if repeat:
                            backend['warm_inference_ms'].append(detector.last_inference_ms)
                    expected=canonical_label(entry['label'])
                    detections=all_rounds[-1]
                    expected_detections=[d for d in detections if d.label==expected]
                    best=max((iou(d.bbox,truth) for d in expected_detections),default=0.)
                    backend['examples'].append({'fixture':str(path.relative_to(ROOT)), 'sha256':sha256(path.read_bytes()).hexdigest(),
                        'source_url':'https://s3.amazonaws.com/open-images-dataset/validation/'+entry['image_id']+'.jpg',
                        'expected_category':expected,'annotated_bbox_pixels':truth,'best_expected_iou':best,
                        'expected_detected_iou_0_5':best>=.5, 'detections':[asdict(d) for d in detections],
                        'repeat_latencies_ms':[detector.last_inference_ms]})
                    if preference=='mps':
                        canvas=frame.copy()
                        for d in detections:
                            if d.label != expected: continue
                            a,b,c,e=map(round,d.bbox)
                            cv2.rectangle(canvas,(a,b),(c,e),(255,170,40),max(1,width//400))
                            cv2.putText(canvas,f'{d.label} {d.confidence:.2f}',(a,max(20,b-7)),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,170,40),2)
                        if expected_detections:
                            cv2.imwrite(str(target.parent/f'safety-{entry["image_id"]}.jpg'),canvas)
                detector.reset_tracking()
                video=cv2.VideoCapture(str(ROOT/'tests/fixtures/vtest.avi'))
                categories=Counter(); tracked=0; frames=0
                try:
                    for _ in range(30):
                        ok,frame=video.read()
                        if not ok:break
                        output=detector.infer(frame)
                        frames+=1
                        categories.update(d.label for d in output)
                        tracked+=sum(d.track_id is not None for d in output)
                finally:video.release()
                backend['recorded_video']={'fixture':'tests/fixtures/vtest.avi','frames':frames,'category_observations':dict(categories),'observations_with_track_id':tracked,
                                           'note':'Numerical ID association was executed; this does not establish identity correctness through occlusion.'}
                backend['warm_mean_inference_ms']=statistics.mean(backend['warm_inference_ms'])
                backend['fallback_reason']=detector.fallback_reason
                backend['matched_selected_examples']=sum(x['expected_detected_iou_0_5'] for x in backend['examples'])
                backend['demonstrated_extra_categories']=sorted({x['expected_category'] for x in backend['examples'] if x['expected_detected_iou_0_5']})
                print(preference,backend['demonstrated_extra_categories'],backend['warm_mean_inference_ms'],flush=True)
                del detector
            report['passed']=bool(report['backends']) and all(b.get('demonstrated_extra_categories') and b.get('recorded_video',{}).get('frames')==30 for b in report['backends'] if 'actual' in b) and not attempts
    except Exception as exc:
        report['error_type']=type(exc).__name__;report['error']=str(exc)
    finally:
        target.write_text(json.dumps(report,indent=2)+'\n')
        print(target,flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
