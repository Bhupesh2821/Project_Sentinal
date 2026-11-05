#!/usr/bin/env python3
"""Execute actual local object detection on selected public safety/tool photos.

Preserves every miss, separates exact-label and generic-helmet matches, and
never treats repeated stills as moving-object identity evidence.
"""
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import socket
import statistics
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sentinal.config import AppConfig
from sentinal.vision.detector import YOLODetector
from sentinal.vision.object_catalog import allowed_class_ids, canonical_label
from tools.verify_safety_tools import iou


def main():
    import cv2
    import torch
    from ultralytics import YOLO
    from ultralytics.trackers import register_tracker
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models',nargs='+',default=['models/yolov8n-oiv7.pt'])
    parser.add_argument('--output',default='docs/evidence/camera-cctv-catalog-2026-10-28/safety-comparison-2026-10-29.json')
    args=parser.parse_args()
    destination=(ROOT/args.output).resolve()
    if not destination.is_relative_to(ROOT):raise ValueError('Output must stay inside the project')
    fixtures=[]
    for name in ['selected.json','extra-selection.json']:
        values=json.loads((ROOT/'work/openimages-safety'/name).read_text())
        fixtures.extend(entry for entries in values.values() for entry in entries)
    attempts=[]
    def denied(*args,**kwargs):
        attempts.append('A Python network call was blocked')
        raise RuntimeError('Offline verification denies Python network calls')
    report={'test':'Production local detector and ByteTrack on selected public safety/tool photos',
            'date':'2026-10-29','confidence_threshold':.25,'inference_size':640,
            'fixture_count':len(fixtures),'python_network_calls_denied':True,'network_attempts':attempts,
            'limitations':'Selected annotated close-up photos are biased examples, not a calibrated accuracy estimate or field/PPE-compliance validation. Repeated stills only execute tracker association, not moving-object identity correctness. Timings can overlap independent verification activity.',
            'camera_opened':False,'camera_images_saved':False,'models':[],'execution_passed':False}
    try:
        with patch.object(socket.socket,'connect',denied),patch.object(socket,'create_connection',denied),patch.object(socket,'getaddrinfo',denied):
            for model_path in args.models:
                weights=(ROOT/model_path).resolve()
                if not weights.is_relative_to(ROOT) or not weights.is_file():raise ValueError('Expected local weights are unavailable')
                model_report={'model_path':str(weights.relative_to(ROOT)),'sha256':sha256(weights.read_bytes()).hexdigest(),'backends':[]}
                report['models'].append(model_report)
                for preference in ['cpu','mps']:
                    if preference=='mps' and not torch.backends.mps.is_available():continue
                    detector=YOLODetector(AppConfig(model_path=str(weights),device=preference))
                    detector.load()
                    backend={'requested':preference,'actual':detector.device,'raw_class_count':len(detector.model.names),
                             'permitted_class_count':len(allowed_class_ids(detector.model.names)),'examples':[],'warm_latency_ms':[]}
                    model_report['backends'].append(backend)
                    for entry in fixtures:
                        path=ROOT/'work/openimages-safety'/(entry['image_id']+'.jpg')
                        frame=cv2.imread(str(path))
                        if frame is None:raise ValueError('Selected real fixture does not decode')
                        height,width=frame.shape[:2]
                        a,b,c,d=entry['bbox'];truth=(a*width,b*height,c*width,d*height)
                        detector.reset_tracking()
                        rounds=[]
                        for repeat in range(2):
                            detections=detector.infer(frame)
                            rounds.append(detector.last_inference_ms)
                        backend['warm_latency_ms'].append(rounds[-1])
                        expected=canonical_label(entry['label'])
                        exact=max((iou(d.bbox,truth) for d in detections if d.label==expected),default=0.)
                        generic=max((iou(d.bbox,truth) for d in detections if expected=='bicycle helmet' and d.label=='helmet'),default=0.)
                        example={'fixture':str(path.relative_to(ROOT)),'sha256':sha256(path.read_bytes()).hexdigest(),
                                 'source_url':'https://s3.amazonaws.com/open-images-dataset/validation/'+path.name,
                                 'expected_category':expected,'annotated_bbox_pixels':truth,'exact_category_iou':exact,'exact_match_iou_0_5':exact>=.5,
                                 'generic_helmet_iou':generic,'generic_helmet_match_iou_0_5':generic>=.5,
                                 'repeat_latency_ms':rounds,'detections':[asdict(d) for d in detections]}
                        backend['examples'].append(example)
                        print(weights.name,preference,path.name,expected,'exact',round(exact,3),'generic',round(generic,3),flush=True)
                    backend['exact_matches']=sum(x['exact_match_iou_0_5'] for x in backend['examples'])
                    backend['generic_helmet_matches']=sum(x['generic_helmet_match_iou_0_5'] for x in backend['examples'])
                    backend['demonstrated_exact_categories']=sorted({x['expected_category'] for x in backend['examples'] if x['exact_match_iou_0_5']})
                    backend['observed_warm_mean_ms']=statistics.mean(backend['warm_latency_ms'])
                    backend['fallback_reason']=detector.fallback_reason
                    del detector
            report['execution_passed']=not attempts and bool(report['models']) and all(len(b['examples'])==len(fixtures) for m in report['models'] for b in m['backends'])
    except Exception as exc:
        report['error_type']=type(exc).__name__;report['error']=str(exc)
    finally:
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(report,indent=2)+'\n')
        print(destination,flush=True)
    return 0 if report['execution_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
