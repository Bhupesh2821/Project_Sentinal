"""Temporal observations are possible hazards, never verified emergencies."""
from dataclasses import dataclass, asdict
from datetime import datetime
import math
from uuid import uuid4

STATES=frozenset({'OBSERVED','CANDIDATE','ALERTED','ACKNOWLEDGED','VERIFIED','DISMISSED','CLOSED'})
CATEGORIES=frozenset({'weapon_handgun','weapon_longgun','weapon_knife','weapon_firearm','fire','smoke','ghs_flammable','ghs_toxic','ghs_corrosive','ghs_oxidizing','ghs_explosive','ghs_gas_pressure','ghs_health'})
TRANSITIONS={'OBSERVED':{'CANDIDATE','CLOSED'},'CANDIDATE':{'ALERTED','CLOSED'},'ALERTED':{'ACKNOWLEDGED','DISMISSED'},'ACKNOWLEDGED':{'VERIFIED','DISMISSED'},'VERIFIED':{'CLOSED'},'DISMISSED':{'CLOSED'},'CLOSED':set()}

def _number(value):
    try:return type(value) in (int,float) and math.isfinite(value) and value>=0
    except (OverflowError,ValueError):return False

def validate_timestamp(value):
    if not isinstance(value,str) or len(value)>64:raise ValueError('A timezone-aware ISO timestamp is required')
    parsed=datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:raise ValueError('A timezone-aware ISO timestamp is required')
    return value

def _identifier(value,label):
    if not isinstance(value,str) or not value or len(value)>256 or any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError(label+' is missing or invalid')
    return value

def _bbox(value):
    if len(value)!=4 or not all(_number(v) for v in value):raise ValueError('Bounding boxes require four finite nonnegative coordinates')
    result=tuple(float(v) for v in value)
    if result[2]<=result[0] or result[3]<=result[1]:raise ValueError('Bounding box must have positive area')
    return result

def box_iou(a,b):
    inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
    return inter/union if union>0 else 0.0

@dataclass(frozen=True)
class TemporalRule:
    confidence_threshold:float=.6
    min_consecutive:int=3
    persistence_s:float=1.0
    max_gap_s:float=.75
    cooldown_s:float=30.0
    severity:int=3
    iou_threshold:float=.3
    def __post_init__(self):
        if not _number(self.confidence_threshold) or not .05<=self.confidence_threshold<=1:raise ValueError('Confidence must be .05 to 1')
        if type(self.min_consecutive) is not int or not 2<=self.min_consecutive<=100:raise ValueError('Consecutive samples must be 2 to 100')
        for value,low,high,label in [(self.persistence_s,0,120,'Persistence'),(self.max_gap_s,.05,30,'Maximum gap'),(self.cooldown_s,0,3600,'Cooldown'),(self.iou_threshold,.05,1,'Association IoU')]:
            if not _number(value) or not low<=value<=high:raise ValueError(label+' is invalid')
        if type(self.severity) is not int or not 1<=self.severity<=4:raise ValueError('Severity must be 1 to 4 independently of confidence')

@dataclass(frozen=True)
class Incident:
    incident_id:str
    source_id:str
    session_id:str
    category:str
    status:str
    confidence:float
    severity:int
    model_id:str
    model_version:str
    bbox:tuple[float,float,float,float]
    track_id:int|None
    first_seen:str
    last_seen:str
    alerted_at:str|None=None
    alert_latency_ms:float|None=None
    def __post_init__(self):
        for value,label in [(self.incident_id,'Incident ID'),(self.source_id,'Source ID'),(self.session_id,'Session ID'),(self.model_id,'Model ID'),(self.model_version,'Model version')]:_identifier(value,label)
        if self.category not in CATEGORIES or self.status not in STATES:raise ValueError('Unsupported incident category or status')
        if not _number(self.confidence) or self.confidence>1:raise ValueError('Invalid confidence')
        if type(self.severity) is not int or not 1<=self.severity<=4:raise ValueError('Invalid severity')
        object.__setattr__(self,'bbox',_bbox(self.bbox))
        if self.track_id is not None and (type(self.track_id) is not int or self.track_id<0):raise ValueError('Invalid track ID')
        validate_timestamp(self.first_seen);validate_timestamp(self.last_seen)
        if datetime.fromisoformat(self.last_seen)<datetime.fromisoformat(self.first_seen):raise ValueError('Last observation precedes the first observation')
        if self.alerted_at is not None:
            validate_timestamp(self.alerted_at)
            if datetime.fromisoformat(self.alerted_at)<datetime.fromisoformat(self.first_seen):raise ValueError('Alert precedes the first observation')
        if self.alert_latency_ms is not None and not _number(self.alert_latency_ms):raise ValueError('Invalid alert latency')
    @property
    def title(self):return 'POSSIBLE '+self.category.replace('weapon_','').replace('ghs_','GHS ').replace('_',' ').upper()
    def to_dict(self):return asdict(self)


class TemporalEventEngine:
    """Bounded single-owner state. Call once per fresh detector sample, even empty."""
    def __init__(self,default_rule=None,camera_rules=None,category_rules=None,max_tracks=256):
        self.default_rule=default_rule or TemporalRule()
        self.camera_rules=dict(camera_rules or {})
        self.category_rules=dict(category_rules or {})
        if any(not isinstance(r,TemporalRule) for r in [self.default_rule,*self.camera_rules.values(),*self.category_rules.values()]):raise ValueError('Use validated TemporalRule instances')
        if type(max_tracks) is not int or not 8<=max_tracks<=4096:raise ValueError('Track bound must be 8 to 4096')
        self.max_tracks=max_tracks;self._tracks={};self._sessions={};self._last_time={};self._cooldowns=[]
    def reset(self,source_id=None):
        if source_id is None:
            self._tracks.clear();self._sessions.clear();self._last_time.clear();self._cooldowns.clear()
        else:
            self._tracks={k:v for k,v in self._tracks.items() if v['source_id']!=source_id}
            self._sessions.pop(source_id,None);self._last_time.pop(source_id,None)
            self._cooldowns=[c for c in self._cooldowns if c['source_id']!=source_id]
    def _rule(self,source,category):
        return self.camera_rules.get((source,category),self.camera_rules.get(source,self.category_rules.get(category,self.default_rule)))
    def _incident(self,state,status,timestamp,now):
        obs=state['observation']
        return Incident(state['id'],state['source_id'],state['session_id'],obs.category,status,float(obs.confidence),state['rule'].severity,obs.model_id,obs.model_version,tuple(obs.bbox),obs.track_id,state['first_timestamp'],timestamp,timestamp if status=='ALERTED' else None,max(0,(now-state['first_time'])*1000) if status=='ALERTED' else None)
    def process(self,source_id,session_id,observations,timestamp,source_time):
        _identifier(source_id,'Source ID');_identifier(session_id,'Session ID');validate_timestamp(timestamp)
        if not _number(source_time):raise ValueError('Source time must be finite and nonnegative')
        now=float(source_time)
        if self._sessions.get(source_id)!=session_id:
            self.reset(source_id)
            if len(self._sessions)>=self.max_tracks:self.reset(next(iter(self._sessions)))
            self._sessions[source_id]=session_id
        previous=self._last_time.get(source_id)
        if previous is not None and now<=previous:
            if now==previous:return ()
            self.reset(source_id);self._sessions[source_id]=session_id
        self._last_time[source_id]=now
        self._cooldowns=[c for c in self._cooldowns if c['source_id']!=source_id or now-c['time']<=c['duration']]
        for key,state in list(self._tracks.items()):
            if state['source_id']==source_id and now-state['last_time']>state['rule'].max_gap_s:del self._tracks[key]
        emitted=[];used=set()
        for obs in observations:
            if getattr(obs,'category',None) not in CATEGORIES:continue
            category=obs.category;rule=self._rule(source_id,category)
            confidence=getattr(obs,'confidence',None)
            if not _number(confidence) or confidence>1 or confidence<rule.confidence_threshold:continue
            try:
                bbox=_bbox(obs.bbox);_identifier(obs.model_id,'Model ID');_identifier(obs.model_version,'Model version')
                track_id=obs.track_id
                if track_id is not None and (type(track_id) is not int or track_id<0):continue
            except (ValueError,TypeError,AttributeError):continue
            candidates=[];duplicate=False
            for key,state in self._tracks.items():
                if state['source_id']!=source_id or state['session_id']!=session_id or state['category']!=category or state['model_id']!=obs.model_id or state['model_version']!=obs.model_version:continue
                overlap=box_iou(state['bbox'],bbox);same_id=track_id is not None and state['track_id']==track_id
                if key in used:
                    if overlap>=rule.iou_threshold or same_id:duplicate=True
                    continue
                if track_id is not None and state['track_id'] is not None and not same_id:continue
                if overlap>=rule.iou_threshold or same_id:candidates.append((same_id,overlap,key))
            if duplicate:continue
            if candidates:
                _,_,key=max(candidates);state=self._tracks[key]
                if state['last_sample']!=previous and not state['alerted']:
                    state['hits']=0;state['first_time']=now;state['first_timestamp']=timestamp;state['stage']='OBSERVED'
                state['hits']+=1
                state.update(observation=obs,bbox=bbox,track_id=track_id,last_time=now,last_sample=now)
            else:
                if any(c['source_id']==source_id and c['session_id']==session_id and c['category']==category and c['model_id']==obs.model_id and c['model_version']==obs.model_version and now-c['time']<c['duration'] and box_iou(c['bbox'],bbox)>=rule.iou_threshold for c in self._cooldowns):continue
                if len(self._tracks)>=self.max_tracks:
                    oldest=min(self._tracks,key=lambda k:self._tracks[k]['last_time']);del self._tracks[oldest]
                key=str(uuid4())
                state={'id':key,'source_id':source_id,'session_id':session_id,'category':category,'model_id':obs.model_id,'model_version':obs.model_version,'observation':obs,'bbox':bbox,'track_id':track_id,'rule':rule,'first_time':now,'first_timestamp':timestamp,'last_time':now,'last_sample':now,'hits':1,'stage':'OBSERVED','alerted':False}
                self._tracks[key]=state;emitted.append(self._incident(state,'OBSERVED',timestamp,now))
            used.add(key)
            if state['alerted']:continue
            if state['hits']>=2 and state['stage']=='OBSERVED':
                state['stage']='CANDIDATE';emitted.append(self._incident(state,'CANDIDATE',timestamp,now))
            if state['hits']>=rule.min_consecutive and now-state['first_time']>=rule.persistence_s:
                state['stage']='ALERTED';state['alerted']=True;emitted.append(self._incident(state,'ALERTED',timestamp,now))
                self._cooldowns.append({'source_id':source_id,'session_id':session_id,'category':category,'model_id':obs.model_id,'model_version':obs.model_version,'bbox':bbox,'time':now,'duration':rule.cooldown_s})
                self._cooldowns=self._cooldowns[-self.max_tracks:]
        # A missed analysed sample breaks an unconfirmed consecutive sequence.
        # Start a new incident on reappearance, preserving accurate first_seen.
        for key,state in list(self._tracks.items()):
            if state['source_id']==source_id and state['last_sample']!=now and not state['alerted']:
                del self._tracks[key]
        return tuple(emitted)
