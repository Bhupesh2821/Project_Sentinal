"""Actual local specialized inference while Python network connections fail closed."""
from pathlib import Path
import argparse,json,socket,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import cv2
from sentinal.vision.specialized import SpecializedSuite

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',default='docs/evidence/v021-2026-11-03/offline-inference.json')
parser.add_argument('--device',choices=('auto','cpu','mps'),default='auto')
args=parser.parse_args()
attempts=[]
def blocked(*args,**kwargs):
    attempts.append('blocked connection attempt')
    raise AssertionError('Unexpected network access during local inference')
socket.create_connection=blocked
socket.socket.connect=blocked
socket.socket.connect_ex=blocked
socket.socket.sendto=blocked
suite=SpecializedSuite(device=args.device,enabled=('weapons','fire_smoke'),confidence=.35,image_size=640)
report={'test':'Real pinned local model loading + inference with Python socket connections blocked','scope':'Python socket guard; not an OS packet capture','passed':False}
try:
    observations=[]
    for name in ('handgun.jpg','fire.jpg','smoke.jpg'):
        frame=cv2.imread(str(ROOT/'data/v02-evaluation'/name))
        suite.reset_tracking()
        current=suite.infer(frame)
        observations.append({'fixture':name,'categories':[o.category for o in current]})
    report['observations']=observations;report['health']={key:dict(value) for key,value in suite.health.items()};report['network_attempts']=len(attempts)
    report['passed']=not attempts and all(suite.health[k]['status']=='active' for k in ('weapons','fire_smoke')) and all(row['categories'] for row in observations)
except Exception as exc:report['failure']=str(exc)
finally:suite.close()
output=(ROOT/args.output).resolve()
if not output.is_relative_to(ROOT):raise ValueError('Evidence must remain in project')
output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2));raise SystemExit(0 if report['passed'] else 1)
