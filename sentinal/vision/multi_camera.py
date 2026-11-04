"""Bounded camera wall: isolated newest-frame capture, shared serial inference.

Each authorized source has an independent pump/session/tracker namespace. A
slow decoder or reconnect cannot block other sources' capture or inference.
No source opens until request_start(), and no metadata/pixels are persisted.
"""
from collections import deque
from dataclasses import dataclass, replace
import logging
from math import isfinite
import queue
import threading
import time
from uuid import uuid4

import psutil
from PySide6.QtCore import QThread, Signal
from sentinal.config import AppConfig
from sentinal.core.v02_settings import V02Settings
from .detector import YOLODetector
from .specialized import SpecializedSuite
from .types import FOCUS_CLASSES, FramePacket, utc_now
from .object_catalog import safety_tool_label
from .video_source import SourceSpec, VideoSource
from .live_capture import LiveVideoSource

log=logging.getLogger(__name__)


def _make_source(spec,config):
    if spec.kind in {'camera','stream'}:
        return LiveVideoSource(spec,config.camera_width,config.camera_height,
            open_timeout_ms=config.stream_open_timeout_ms,read_timeout_ms=config.stream_read_timeout_ms)
    return VideoSource(spec,config.camera_width,config.camera_height,
        open_timeout_ms=config.stream_open_timeout_ms,read_timeout_ms=config.stream_read_timeout_ms)


@dataclass(frozen=True)
class _InputFrame:
    frame:object
    session_id:str
    frame_index:int
    source_time_s:float
    timestamp:str
    received_at:float
    capture_age_ms:float
    dropped_frames:int
    source_fps:float


class _SourcePump(threading.Thread):
    """One newest-frame mailbox; this thread alone opens/reads/closes its source."""
    def __init__(self,selection,config,notify,wake,source_factory=None):
        self.source_id=selection.record.camera_id;self.name_label=selection.record.name
        super().__init__(name='SENTINAL source '+self.source_id[:8],daemon=True)
        self.spec=selection.spec;self.config=config;self._notify=notify;self._wake=wake
        self._factory=source_factory or _make_source
        self._stop_event=threading.Event();self._lock=threading.Lock()
        self._latest=None;self._source=None;self._state='loading';self._session=''
        self.overwritten=0;self.resources_released=True
    @property
    def state(self):
        with self._lock:return self._state
    @property
    def session_id(self):
        with self._lock:return self._session
    def _status(self,state,message):
        with self._lock:
            self._state=state
            if state in {'reconnecting','error','stopped','eof'}:self._latest=None
        self._notify(self.source_id,state,message);self._wake.set()
    def request_stop(self):
        self._stop_event.set();self._wake.set()
        # Signal the existing isolated capture process, without racing a second
        # close() against the source owner's open/read/cleanup calls.
        source=self._source
        signal=getattr(source,'_stop',None)
        if signal is not None:
            try:signal.set()
            except Exception:pass
    def take_latest(self):
        with self._lock:packet,self._latest=self._latest,None;return packet
    def run(self):
        failures=0
        try:
            while not self._stop_event.is_set():
                source=None;connection_started=time.monotonic();got_frame=False
                try:
                    self._status('loading' if failures==0 else 'reconnecting','Opening the selected source…')
                    source=self._factory(self.spec,self.config);self._source=source
                    self.resources_released=False;source.open()
                    with self._lock:self._session=str(uuid4());self._latest=None
                    self.overwritten=0
                    self._status('ready','Source connected · waiting for local inference')
                    while not self._stop_event.is_set():
                        read_started=time.monotonic();frame=source.read();received=time.monotonic()
                        if self._stop_event.is_set():break
                        if frame is None:
                            if self.spec.kind=='file':self._status('eof','Video complete · releasing source');return
                            raise RuntimeError('No fresh live frame')
                        got_frame=True
                        if received-connection_started>=5:failures=0
                        with self._lock:
                            if self._latest is not None:self.overwritten+=1
                            self._latest=_InputFrame(frame,self._session,int(source.frame_index),float(source.source_time_s),
                                utc_now(),received,float(getattr(source,'frame_age_ms',0)),
                                int(getattr(source,'dropped_frames',0))+self.overwritten,float(getattr(source,'fps',0)))
                        self._wake.set()
                        # Recorded fixtures must play at source speed rather than
                        # racing to EOF before serial inference can consume them.
                        if self.spec.kind=='file':
                            fps=float(getattr(source,'fps',0));interval=1/fps if fps>0 else .04
                            self._stop_event.wait(max(0,interval-(time.monotonic()-read_started)))
                except Exception:
                    if self._stop_event.is_set():break
                    failures+=1
                    if self.spec.kind!='stream' or failures>self.config.stream_reconnect_attempts:
                        self._status('error','Selected source unavailable. Check access, connection, codec or camera permission.');return
                    self._status('reconnecting',f'Connection lost · retry {failures}/{self.config.stream_reconnect_attempts}')
                finally:
                    if source is not None:
                        try:source.close()
                        except Exception:
                            log.warning('Camera wall capture cleanup failed for source %s',self.source_id)
                            self.resources_released=False
                        else:self.resources_released=True
                    self._source=None
                if not self.resources_released:
                    self._status('error','Capture cleanup failed. Close SENTINAL before retrying this source.');return
                if self._stop_event.is_set():break
                self._stop_event.wait(min(10.,self.config.stream_reconnect_delay_s*2**max(0,failures-1)))
        finally:
            if self._stop_event.is_set():self._status('stopped','Monitoring stopped · source released' if self.resources_released else 'Monitoring stopped · capture cleanup failed')
            elif self.state=='eof':
                self._notify(self.source_id,'eof','Video complete · source released' if self.resources_released else 'Video complete · capture cleanup failed')
            self._wake.set()


class MultiCameraWorker(QThread):
    """Maximum eight sources with one shared ordinary and specialized model set."""
    state_changed=Signal(str,str,str)
    error=Signal(str,str)
    MAX_CAMERAS=8
    def __init__(self,config,parent=None,max_cameras=8,*,source_factory=None,detector_factory=None,suite_factory=None):
        super().__init__(parent)
        if not isinstance(config,AppConfig):raise ValueError('Use a validated application configuration')
        if type(max_cameras) is not int or not 1<=max_cameras<=8:raise ValueError('Camera wall supports1–8sources')
        self.config=config;self.max_cameras=max_cameras
        self._source_factory=source_factory;self._detector_factory=detector_factory or YOLODetector
        self._suite_factory=suite_factory or SpecializedSuite
        self._commands=queue.Queue(maxsize=16);self._command_lock=threading.Lock()
        self._lock=threading.RLock();self._wake=threading.Event();self._shutdown=threading.Event()
        self._pumps={};self._pending={};self._retiring=[];self._latest={};self._sessions={}
        self._states={};self._round_robin=0;self._consumer=None
        self._blocked_sources=set();self._blocked_resources=set()
        self._options={'confidence':config.confidence,'image_size':config.image_size,'hazards_enabled':False,'hazard_settings':V02Settings(),'category_filter':'all'}
        self.detector=None;self.hazard_suite=None;self._hazard_signature=None
        self._last_hazard={};self._times={};self._latencies={};self._metrics={};self._metrics_at=0.;self._process=None
    @property
    def source_ids(self):
        with self._lock:return tuple(self._pumps)
    @property
    def is_monitoring(self):
        with self._lock:return bool(self._pumps or self._pending or self._retiring)
    def _enqueue(self,command,value=None):
        if self._shutdown.is_set() and command!='shutdown':return False
        with self._command_lock:
            items=[]
            while True:
                try:items.append(self._commands.get_nowait())
                except queue.Empty:break
            if command in {'start','shutdown'}:items=[item for item in items if item[0]!='start']
            if command=='shutdown' or (command=='stop' and value is None):items=[]
            for item in items[-15:]:self._commands.put_nowait(item)
            self._commands.put_nowait((command,value))
        self._wake.set();return True
    def request_start(self,selections):
        selections=tuple(selections)
        if not 1<=len(selections)<=self.max_cameras:raise ValueError(f'Select1–{self.max_cameras}cameras')
        identifiers=set();camera_keys=set();stream_keys=set()
        from urllib.parse import urlsplit
        for selection in selections:
            ident=getattr(getattr(selection,'record',None),'camera_id',None);spec=getattr(selection,'spec',None)
            if not isinstance(ident,str) or not ident or len(ident)>256 or any(ord(c)<32 for c in ident):raise ValueError('Each source requires a valid camera ID')
            if ident in identifiers:raise ValueError('A camera can be selected only once')
            if not isinstance(spec,SourceSpec):raise ValueError('Each camera requires a validated source')
            identifiers.add(ident)
            if spec.kind=='camera':
                if not spec.camera_device_id:raise ValueError('Choose an exact local camera identity')
                if spec.camera_key in camera_keys:raise ValueError('The same local camera cannot open twice')
                camera_keys.add(spec.camera_key)
            elif spec.kind=='stream':
                parsed=urlsplit(spec.value);key=(parsed.scheme,parsed.hostname,parsed.port,parsed.path,parsed.query)
                if key in stream_keys:raise ValueError('The same network stream cannot open twice')
                stream_keys.add(key)
        return self._enqueue('start',selections)
    def request_stop(self,source_id=None):
        with self._lock:pumps=[pump for ident,pump in self._pumps.items() if source_id is None or ident==source_id]
        for pump in pumps:pump.request_stop()
        return self._enqueue('stop',source_id)
    def request_shutdown(self):
        self._shutdown.set()
        with self._lock:pumps=list(self._pumps.values())+list(self._retiring)
        for pump in pumps:pump.request_stop()
        self._enqueue('shutdown');self._wake.set()
    def set_options(self,confidence=None,image_size=None,hazards_enabled=None,hazard_settings=None,model_path=None,category_filter=None):
        with self._lock:
            values=dict(self._options)
            if model_path is not None and model_path!=self.config.model_path:
                candidate=replace(self.config,model_path=model_path)
                if self.is_monitoring:raise ValueError('Stop the camera wall before changing its object model')
                self.config=candidate
            if confidence is not None:
                if type(confidence) not in (int,float) or not isfinite(confidence) or not .05<=confidence<=.95:raise ValueError('Object confidence must be.05–.95')
                values['confidence']=float(confidence)
            if image_size is not None:
                if type(image_size) is not int or image_size not in (320,480,640,960):raise ValueError('Unsupported inference size')
                values['image_size']=image_size
            if hazards_enabled is not None:
                if type(hazards_enabled) is not bool:raise ValueError('Hazard activation must be explicit')
                values['hazards_enabled']=hazards_enabled
            if hazard_settings is not None:
                if not isinstance(hazard_settings,V02Settings):raise ValueError('Use validated hazard settings')
                values['hazard_settings']=hazard_settings
            if category_filter is not None:
                if not isinstance(category_filter,str) or category_filter not in {'all','focus','safety'}:raise ValueError('Unknown category filter')
                values['category_filter']=category_filter
            self._options=values
        self._wake.set()
    def set_incident_consumer(self,consumer=None):
        if consumer is not None and not callable(consumer):raise ValueError('Incident consumer must be callable')
        with self._lock:self._consumer=consumer
    def take_latest(self):
        with self._lock:result,self._latest=self._latest,{};return result
    def _pump_state(self,ident,state,message):
        public='loading' if state=='ready' else state
        with self._lock:
            self._states[ident]=public
            if state in {'reconnecting','error','stopped','eof'}:self._latest.pop(ident,None)
        self.state_changed.emit(ident,public,message)
        if state=='error':self.error.emit(ident,message)
    def _reset_session(self,ident):
        old=self._sessions.pop(ident,None)
        if old is not None:
            if self.detector is not None:self.detector.reset_tracking(source_id=old)
            if self.hazard_suite is not None:self.hazard_suite.reset_tracking(source_id=old)
        self._last_hazard.pop(ident,None);self._times.pop(ident,None);self._latencies.pop(ident,None)
    def _retire(self,ident):
        with self._lock:
            self._pending.pop(ident,None);pump=self._pumps.pop(ident,None);self._latest.pop(ident,None)
            if pump is not None:
                self._states[ident]='stopping'
                self.state_changed.emit(ident,'stopping','Stopping selected source…')
                pump.request_stop();self._retiring.append(pump)
        self._reset_session(ident)
        if pump is None:self.state_changed.emit(ident,'stopped','Monitoring stopped')
    def _apply_start(self,selections):
        selected={selection.record.camera_id:selection for selection in selections}
        with self._lock:active=dict(self._pumps)
        # No implicit change of a running camera's endpoint/profile.
        if any(ident in active and active[ident].spec!=selection.spec for ident,selection in selected.items()):
            self.error.emit('','Stop a camera before changing its connection. Existing sources remain active.');return
        for ident in list(active):
            if ident not in selected:self._retire(ident)
        with self._lock:
            self._pending={ident:selection for ident,selection in selected.items() if ident not in self._pumps}
        for ident in self._pending:self.state_changed.emit(ident,'loading','Preparing selected source · waiting for an available capture slot')
    @staticmethod
    def _resource_key(spec):
        # A saved-camera alias must not reopen a physical capture while its
        # previous owner is still closing. File readers can be independent.
        if spec.kind=='camera':return ('camera',spec.camera_key)
        if spec.kind=='stream':
            from urllib.parse import urlsplit
            parsed=urlsplit(spec.value)
            return ('stream',parsed.scheme,parsed.hostname,parsed.port,parsed.path,parsed.query)
        return None
    def _block_failed_release(self,pump):
        self._blocked_sources.add(pump.source_id)
        resource=self._resource_key(pump.spec)
        if resource is not None:self._blocked_resources.add(resource)
        self.error.emit(pump.source_id,'Capture cleanup failed. Close SENTINAL before retrying.')
    def _reap(self):
        with self._lock:
            # A pump may exit between two liveness samples. Classify it once
            # per reap so failed cleanup can never vanish from both lists.
            retired=[];retiring=[]
            for pump in self._retiring:
                (retiring if pump.is_alive() else retired).append(pump)
            self._retiring=retiring
            ended=[ident for ident,pump in self._pumps.items() if not pump.is_alive()]
            for ident in ended:
                pump=self._pumps.pop(ident);self._latest.pop(ident,None)
                if not pump.resources_released:self._block_failed_release(pump)
        for ident in ended:
            self._reset_session(ident)
            with self._lock:self._states.pop(ident,None)
        for pump in retired:
            with self._lock:
                if pump.source_id not in self._pumps:self._states.pop(pump.source_id,None)
            if not pump.resources_released:self._block_failed_release(pump)
        with self._lock:
            reserved_ids={pump.source_id for pump in self._retiring}
            reserved_resources={self._resource_key(pump.spec) for pump in (*self._pumps.values(),*self._retiring)}-{None}
            for ident,selection in tuple(self._pending.items()):
                resource=self._resource_key(selection.spec)
                if ident in self._blocked_sources or resource is not None and resource in self._blocked_resources:
                    self._pending.pop(ident);self._pump_state(ident,'error','Previous capture cleanup failed. Close SENTINAL before retrying this source.');continue
                if len(self._pumps)+len(self._retiring)>=self.max_cameras:break
                if ident in reserved_ids or resource is not None and resource in reserved_resources:continue
                self._pending.pop(ident)
                pump=_SourcePump(selection,self.config,self._pump_state,self._wake,self._source_factory)
                self._pumps[ident]=pump
                if resource is not None:reserved_resources.add(resource)
                pump.start()
    def _configure_models(self,options):
        size=options['image_size']
        current=getattr(self.detector,'config',None)
        if current is not None and current.model_path!=self.config.model_path:self.detector=None
        if self.detector is None:self.detector=self._detector_factory(replace(self.config,image_size=size))
        elif getattr(self.detector,'config',None) is not None and self.detector.config.image_size!=size:
            self.detector.config=replace(self.detector.config,image_size=size)
        settings=options['hazard_settings']
        enabled=tuple(settings.detectors) if options['hazards_enabled'] else ()
        threshold=getattr(settings,'display_confidence',.25)
        categories=dict(getattr(settings,'category_thresholds',{}))
        signature=(enabled,threshold,size,settings.detect_fire,settings.detect_smoke,tuple(sorted(categories.items())))
        if signature!=self._hazard_signature:
            if not enabled:
                if self.hazard_suite is not None:self.hazard_suite.close()
                self.hazard_suite=None
            else:
                kwargs={'enabled':enabled,'confidence':threshold,'image_size':size,'detect_fire':settings.detect_fire,'detect_smoke':settings.detect_smoke,'category_thresholds':categories}
                if self.hazard_suite is None:self.hazard_suite=self._suite_factory(device=self.config.device,**kwargs)
                else:self.hazard_suite.configure(**kwargs)
            self._hazard_signature=signature;self._last_hazard.clear()
    def _infer(self,ident,pump,entry):
        with self._lock:options=dict(self._options)
        if self._sessions.get(ident)!=entry.session_id:
            self._reset_session(ident);self._sessions[ident]=entry.session_id
        self._configure_models(options)
        started=time.monotonic()
        detections=self.detector.infer(entry.frame,options['confidence'],source_id=entry.session_id)
        if options['category_filter']=='focus':detections=tuple(d for d in detections if d.label in FOCUS_CLASSES)
        elif options['category_filter']=='safety':detections=tuple(d for d in detections if safety_tool_label(d.label))
        base_ms=float(self.detector.last_inference_ms)
        hazards=();sampled=False;hazard_ms=0.;health={}
        if self.hazard_suite is not None:
            previous=self._last_hazard.get(ident);interval=options['hazard_settings'].sample_interval_s
            if previous is None or entry.source_time_s<previous or entry.source_time_s-previous+1e-6>=interval:
                hazard_started=time.monotonic()
                hazards=tuple(self.hazard_suite.infer(entry.frame,frame_index=entry.frame_index,source_time_s=entry.source_time_s,source_id=entry.session_id))
                hazard_ms=(time.monotonic()-hazard_started)*1000;sampled=True;self._last_hazard[ident]=entry.source_time_s
            health={key:{**value,'measurement_scope':'this analyzed sample' if sampled else 'shared model last inference; this frame unsampled'} for key,value in self.hazard_suite.health.items()}
        completed=time.monotonic()
        if pump.state not in {'ready'} or pump.session_id!=entry.session_id or pump._stop_event.is_set():return
        times=self._times.setdefault(ident,deque(maxlen=60));times.append(completed)
        latencies=self._latencies.setdefault(ident,deque(maxlen=60));latencies.append(base_ms+hazard_ms)
        fps=(len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0.
        if completed-self._metrics_at>=1:
            if self._process is None:self._process=psutil.Process()
            self._metrics={'memory_rss_mb':self._process.memory_info().rss/1024**2,'cpu_percent':self._process.cpu_percent(None) if self._metrics_at else None}
            self._metrics_at=completed
        packet=FramePacket(frame=entry.frame,detections=tuple(detections),session_id=entry.session_id,
            source=pump.name_label,frame_index=entry.frame_index,timestamp=entry.timestamp,source_time_s=entry.source_time_s,
            fps=fps,inference_ms=base_ms+hazard_ms,average_inference_ms=sum(latencies)/len(latencies),
            device=self.detector.device,frame_age_ms=max(0,entry.capture_age_ms+(completed-entry.received_at)*1000) if pump.spec.kind!='file' else 0.,
            dropped_frames=entry.dropped_frames,model_name=self.config.weights.name,hazards=hazards,hazard_sampled=sampled,
            detector_health=health,diagnostics={**self._metrics,'base_inference_ms':base_ms,'hazard_inference_ms':hazard_ms,
                'queue_wait_ms':max(0,(started-entry.received_at)*1000),'source_fps':entry.source_fps,
                'inference_owner':'shared serial camera wall','active_sources':len(self.source_ids),'category_filter':options['category_filter']})
        with self._lock:
            consumer=self._consumer
            first=self._states.get(ident)!='running';self._states[ident]='running';self._latest[ident]=packet
        if first:self.state_changed.emit(ident,'running','Monitoring · shared local inference active')
        if sampled and consumer is not None:
            try:consumer(packet,ident)
            except Exception:
                log.warning('Camera wall incident consumer failed for source %s',ident)
                self.error.emit(ident,'Incident assessment is unavailable for this source; video inference can continue.')
    def run(self):
        try:
            while not self._shutdown.is_set():
                for _ in range(16):
                    try:command,value=self._commands.get_nowait()
                    except queue.Empty:break
                    if command=='shutdown':break
                    if command=='start':self._apply_start(value)
                    elif command=='stop':
                        with self._lock:identifiers=list(set(self._pumps)|set(self._pending)) if value is None else [value]
                        for ident in identifiers:self._retire(ident)
                self._reap()
                with self._lock:items=list(self._pumps.items())
                progressed=False
                if items:
                    start=self._round_robin%len(items)
                    for offset in range(len(items)):
                        ident,pump=items[(start+offset)%len(items)];entry=pump.take_latest()
                        if entry is None:continue
                        self._round_robin=(start+offset+1)%len(items)
                        try:self._infer(ident,pump,entry)
                        except Exception:
                            log.exception('Camera wall local inference failed for source %s',ident)
                            self._retire(ident)
                            self._pump_state(ident,'error','Local inference failed for this source. Check Diagnostics and restart it.')
                        progressed=True;break
                if not progressed:self._wake.wait(.02);self._wake.clear()
        except Exception:
            log.exception('Shared camera wall worker failed')
            self.error.emit('','Camera wall stopped unexpectedly. Close and reopen the wall before retrying.')
        finally:
            with self._lock:
                self._pending.clear();pumps=list(self._pumps.values())+self._retiring
                self._pumps={};self._retiring=[];self._latest={}
            for pump in pumps:pump.request_stop()
            # All source owners stop concurrently; one common deadline bounds
            # shutdown rather than multiplying timeouts by the camera count.
            deadline=time.monotonic()+self.config.stream_open_timeout_ms/1000+self.config.stream_read_timeout_ms/1000+5
            for pump in pumps:pump.join(max(0,deadline-time.monotonic()))
            for pump in pumps:
                if pump.is_alive() or not pump.resources_released:self.error.emit(pump.source_id,'Source cleanup did not complete; close SENTINAL before another session.')
            for ident in list(self._sessions):self._reset_session(ident)
            if self.hazard_suite is not None:self.hazard_suite.close()
