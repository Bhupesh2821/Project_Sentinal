"""Optional local hazard observations, separate from emergency/intent decisions.

Each result is an uncertain visual candidate. Temporal rules and human review
belong to the incident layer. Runtime never downloads model weights.
"""
from dataclasses import dataclass
from math import isfinite
from time import perf_counter
import logging

log=logging.getLogger(__name__)
import numpy as np
from sentinal.core.device_manager import select_device, synchronize
from sentinal.vision.model_registry import ASSETS, verify_asset
from sentinal.vision.raw_tracking import RawTrackerBank

@dataclass(frozen=True)
class HazardObservation:
    category: str
    confidence: float
    bbox: tuple[float, float, float, float]
    track_id: int | None
    model_id: str
    model_version: str
    detector: str

    def __post_init__(self):
        if not self.category or not self.model_id or not self.model_version:
            raise ValueError('Hazard observations require category and model provenance')
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError('Confidence must be finite from zero to one')
        if len(self.bbox)!=4 or not all(isfinite(v) for v in self.bbox):
            raise ValueError('Hazard box requires four finite coordinates')
        a,b,c,d=self.bbox
        if min(a,b)<0 or c<=a or d<=b:
            raise ValueError('Hazard box must have positive area in source pixels')
        if self.track_id is not None and (type(self.track_id) is not int or self.track_id<0):
            raise ValueError('Tracking ID must be a nonnegative integer or unavailable')

# Only documented, actually present classes are mapped. A generic gun class is
# never renamed handgun or rifle. Additional unvalidated categories are ignored.
CLASS_MAP = {
    'fire': 'fire', 'flame': 'fire', 'smoke': 'smoke',
    'pistol': 'weapon_handgun', 'handgun': 'weapon_handgun',
    'rifle': 'weapon_longgun', 'shotgun': 'weapon_longgun', 'long gun':'weapon_longgun',
    'knife': 'weapon_knife', 'gun': 'weapon_firearm', 'guns': 'weapon_firearm',
}

def _values(value):
    if hasattr(value,'detach'): value=value.detach()
    if hasattr(value,'cpu'): value=value.cpu()
    return value.tolist() if hasattr(value,'tolist') else list(value)

def observations_from_result(result, frame_shape, asset, confidence, track_ids=None, category_thresholds=None):
    if len(frame_shape)<2 or min(frame_shape[:2])<=0:raise ValueError('A positive frame shape is required')
    if not isfinite(confidence) or not 0<=confidence<=1:raise ValueError('Invalid confidence threshold')
    boxes=result.boxes
    if boxes is None: return ()
    coords,scores,classes=_values(boxes.xyxy),_values(boxes.conf),_values(boxes.cls)
    ids=[track_ids.get(i) for i in range(len(coords))] if track_ids is not None else (_values(boxes.id) if boxes.id is not None else [None]*len(coords))
    if not len(coords)==len(scores)==len(classes)==len(ids):
        raise ValueError('Inconsistent specialized detector arrays')
    h,w=frame_shape[:2];out=[]
    for box,score,cls,track in zip(coords,scores,classes,ids):
        try:
            if not isfinite(float(cls)) or int(cls)!=cls:continue
            label=str(result.names[int(cls)]).strip().lower()
            category=CLASS_MAP.get(label)
            if not category or float(score)<(category_thresholds or {}).get(category,confidence):continue
            if asset.key=='fire_smoke' and category not in {'fire','smoke'}:continue
            if asset.key=='weapons' and not category.startswith('weapon_'):continue
            if len(box)!=4:continue
            a,b,c,d=map(float,box)
            if not all(isfinite(v) for v in (a,b,c,d)):continue
            clipped=(max(0.,min(w,a)),max(0.,min(h,b)),max(0.,min(w,c)),max(0.,min(h,d)))
            if track is not None and (not isfinite(float(track)) or int(track)!=track):continue
            out.append(HazardObservation(category,float(score),clipped,int(track) if track is not None else None,asset.model_id,asset.version,asset.key))
        except (ValueError,TypeError,KeyError,IndexError,OverflowError):continue
    return tuple(out)

class SpecializedSuite:
    def __init__(self,device='auto',enabled=(),confidence=.35,image_size=640,detect_fire=True,detect_smoke=True,category_thresholds=None):
        self.detect_fire=bool(detect_fire)
        self.detect_smoke=bool(detect_smoke)
        self._preference=device
        self._models={}
        self._failed=set()
        self.health={}
        self.category_thresholds={}
        self.configure(enabled=enabled,confidence=confidence,image_size=image_size,category_thresholds=category_thresholds or {})

    def configure(self,enabled=None,confidence=None,image_size=None,detect_fire=None,detect_smoke=None,category_thresholds=None,**_):
        if category_thresholds is not None:
            if not isinstance(category_thresholds,dict) or any(key not in set(CLASS_MAP.values()) or type(value) not in (int,float) or not isfinite(value) or not .05<=value<=.99 for key,value in category_thresholds.items()):
                raise ValueError('Category thresholds require supported categories and scores .05–.99')
            self.category_thresholds=dict(category_thresholds)
        if detect_fire is not None:self.detect_fire=bool(detect_fire)
        if detect_smoke is not None:self.detect_smoke=bool(detect_smoke)
        if enabled is not None:
            if any(k not in {'weapons','fire_smoke','ghs'} for k in enabled):
                raise ValueError('Unknown specialized detector module')
            self.enabled=tuple(dict.fromkeys(enabled))
        if confidence is not None:
            if type(confidence) not in (int,float) or not isfinite(confidence) or not .05<=confidence<=.99:
                raise ValueError('Hazard confidence must be .05 to .99')
            self.confidence=float(confidence)
        if image_size is not None:
            if type(image_size) is not int or image_size not in {320,480,640,960}:raise ValueError('Unsupported detector size')
            self.image_size=image_size
        for key in tuple(self._models):
            if key not in self.enabled: del self._models[key]
        for key in {'weapons','fire_smoke','ghs'}:
            self.health.setdefault(key,{'status':'disabled','latency_ms':None,'error':''})
            if key not in self.enabled:self.health[key]={'status':'disabled','latency_ms':None,'error':''}
            elif self.health[key]['status']=='disabled':self.health[key]={'status':'pending','latency_ms':None,'error':''}

    def _load(self,key):
        if key in self._models:return self._models[key]
        asset=ASSETS[key]
        weights=verify_asset(asset)
        from .safe_weights import load_pinned_yolo
        model=load_pinned_yolo(asset)
        expected={'weapons': {0:'Grenade',1:'Gun',2:'Knife',3:'Pistol',4:'handgun',5:'rifle'}, 'fire_smoke': {0:'fire',1:'smoke'}}
        if model.names != expected[key]:raise ValueError('Pinned model classes differ from the reviewed definitions')
        permitted=[int(i) for i,name in model.names.items() if str(name).lower().strip() in CLASS_MAP and ((key=='fire_smoke' and CLASS_MAP[str(name).lower().strip()] in {'fire','smoke'}) or (key=='weapons' and CLASS_MAP[str(name).lower().strip()].startswith('weapon_')))]
        if not permitted:raise ValueError('The detector has no supported trained classes')
        state={'asset':asset,'model':model,'device':select_device(self._preference),'classes':permitted,'tracking':RawTrackerBank()}
        self._models[key]=state
        return state

    def infer(self,frame,frame_index=0,source_time_s=0,source_id="default"):
        if not isinstance(frame,np.ndarray) or frame.dtype!=np.uint8 or frame.ndim!=3 or frame.shape[2]!=3 or not frame.size:
            raise ValueError('Specialized inference requires a nonempty uint8 BGR frame')
        out=[]
        for key in self.enabled:
            started=perf_counter()
            if key in self._failed:continue
            if key=='fire_smoke' and not (self.detect_fire or self.detect_smoke):
                self.health[key]={'status':'disabled','latency_ms':None,'error':''}
                continue
            try:
                if key=='ghs':
                    raise ValueError('Optional GHS pictogram recognition is unavailable in this build.')
                state=self._load(key)
                def run():
                    synchronize(state['device'])
                    result=state['model'].predict(source=frame,mode='predict',classes=state['classes'],conf=.05,iou=.6,imgsz=self.image_size,device=state['device'],verbose=False,save=False,stream=False)[0]
                    synchronize(state['device'])
                    return result
                try:result=run()
                except Exception:
                    if state['device']!='mps':raise
                    state['device']='cpu';state['model'].to('cpu');state['model'].predictor=None
                    result=run()
                track_ids=state['tracking'].associate(result,frame,source_id)
                normalized=observations_from_result(result,frame.shape,state['asset'],self.confidence,track_ids,self.category_thresholds)
                out.extend(o for o in normalized if (o.category!='fire' or self.detect_fire) and (o.category!='smoke' or self.detect_smoke))
                self.health[key]={'status':'active','latency_ms':(perf_counter()-started)*1000,'device':state['device'],'model_id':state['asset'].model_id,'model_version':state['asset'].version,'classes':[state['model'].names[i] for i in state['classes']],'tracking_status':state['tracking'].status(source_id),'raw_predictions':len(result.boxes) if result.boxes is not None else 0,'error':''}
            except Exception as exc:
                log.exception('Specialized detector %s failed; disabled until session reset',key)
                self._failed.add(key)
                message=str(exc) if isinstance(exc,ValueError) else 'Detector failed locally; disable it, check the pinned model and restart monitoring.'
                self.health[key]={'status':'unavailable','latency_ms':(perf_counter()-started)*1000,'error':message}
        return tuple(out)

    def reset_tracking(self,source_id=None):
        from .tracker import reset_model_trackers
        for key,state in self._models.items():
            if isinstance(state,dict):
                reset_model_trackers(state['model'])
                state['tracking'].reset(source_id)
        self._failed.clear()
        for key in self.enabled:self.health[key]={'status':'pending','latency_ms':None,'error':''}

    def close(self):
        self._models.clear();self._failed.clear()
        for key in self.health:self.health[key]={'status':'disabled','latency_ms':None,'error':''}
