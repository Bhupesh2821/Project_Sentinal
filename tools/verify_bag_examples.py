"""Evaluate supplied real COCO128 bag images without substituting detections."""
from pathlib import Path
import argparse,json,hashlib,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sentinal.config import AppConfig
from sentinal.vision.detector import YOLODetector
from sentinal.vision.types import BAG_CLASSES
import cv2

parser=argparse.ArgumentParser()
parser.add_argument('--dataset',type=Path,required=True,help='Extracted COCO128 root with images/ and labels/')
parser.add_argument('--output',type=Path,default=Path('docs/evidence/bag-examples.json'))
args=parser.parse_args()
model=YOLODetector(AppConfig(device='cpu',image_size=640))
report={'model':'yolo11n.pt','confidence':0.25,'image_size':640,'source':'Official COCO128 public asset; static real photos, not moving footage','images':[]}
for label_file in sorted((args.dataset/'labels/train2017').glob('*.txt')):
    labeled_ids={int(line.split()[0]) for line in label_file.read_text().splitlines() if line.strip()}
    if not labeled_ids & {24,26,28}: continue
    photo=args.dataset/'images/train2017'/label_file.with_suffix('.jpg').name
    frame=cv2.imread(str(photo))
    if frame is None: continue
    model.reset_tracking()
    found=model.infer(frame)
    bags=[d for d in found if d.label in BAG_CLASSES]
    report['images'].append({'filename':photo.name,'sha256':hashlib.sha256(photo.read_bytes()).hexdigest(),'annotated_classes':sorted(labeled_ids & {24,26,28}),'bags':[{'label':d.label,'confidence':d.confidence,'bbox':list(d.bbox),'track_id':d.track_id} for d in bags]})
    print(photo.name,[(d.label,round(d.confidence,3)) for d in bags],flush=True)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2)+'\n')
