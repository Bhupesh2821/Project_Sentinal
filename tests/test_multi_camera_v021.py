"""Synthetic concurrency/failure contracts; real RTSP inference is a separate tool."""
import time
from types import SimpleNamespace
from uuid import uuid4
import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication
from sentinal.config import AppConfig
from sentinal.vision.video_source import SourceSpec
from sentinal.vision.types import Detection
from sentinal.vision.multi_camera import MultiCameraWorker


def selection(name='a',kind='file',value=None):
    return SimpleNamespace(record=SimpleNamespace(camera_id=str(uuid4()),name=name),spec=SourceSpec(kind,value or name+'.mp4'))

class FakeSource:
    created=[];failures={};reads={};fps=200;frame_age_ms=0;dropped_frames=0
    def __init__(self,spec,config):
        self.spec=spec;self.config=config;self.frame_index=0;self.source_time_s=0;self.closed=False
        self.created.append(self)
    def open(self):
        if self.failures.get(str(self.spec.value),0):
            self.failures[str(self.spec.value)]-=1;raise RuntimeError('test-only disconnected')
    def read(self):
        self.frame_index+=1;self.source_time_s=self.frame_index/self.fps
        self.reads[str(self.spec.value)]=self.reads.get(str(self.spec.value),0)+1
        if 'eof' in str(self.spec.value) and self.frame_index>8:return None
        if 'drop' in str(self.spec.value) and self.frame_index==5:raise RuntimeError('test-only dropout')
        if self.spec.kind=='stream':time.sleep(.005)
        return np.zeros((48,64,3),np.uint8)
    def close(self):self.closed=True

class FakeDetector:
    created=[]
    def __init__(self,config):
        self.config=config;self.device='cpu';self.last_inference_ms=1.;self.calls=[];self.resets=[]
        self.created.append(self)
    def infer(self,frame,confidence=None,source_id='default'):
        self.calls.append(source_id);time.sleep(.008)
        return (Detection(0,'person',.8,(1,1,30,40),1),)
    def reset_tracking(self,source_id=None):self.resets.append(source_id)

@pytest.fixture
def app():return QCoreApplication.instance() or QCoreApplication([])

@pytest.fixture
def worker(app):
    FakeSource.created=[];FakeSource.failures={};FakeSource.reads={};FakeDetector.created=[]
    owner=MultiCameraWorker(AppConfig(stream_open_timeout_ms=250,stream_read_timeout_ms=250,stream_reconnect_delay_s=.1),source_factory=FakeSource,detector_factory=FakeDetector)
    owner.start();yield owner
    owner.request_shutdown();assert owner.wait(5000)
    assert all(source.closed for source in FakeSource.created)

def wait(app,predicate,timeout=4):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():return
        time.sleep(.003)
    raise AssertionError('Multi-camera state timed out')


def test_no_source_or_model_before_explicit_start(worker):
    assert not FakeSource.created and not FakeDetector.created and not worker.is_monitoring


def test_two_sources_share_one_model_and_fair_bounded_mailboxes(worker,app):
    a,b=selection('a'),selection('b');worker.request_start((a,b))
    received={}
    def ready():
        received.update(worker.take_latest());return len(received)==2
    wait(app,ready)
    assert len(FakeDetector.created)==1
    packets=list(received.values());assert packets[0].session_id!=packets[1].session_id
    assert set(FakeDetector.created[0].calls)=={p.session_id for p in packets}
    time.sleep(.08);assert len(worker.take_latest())<=2
    assert len(worker._pumps)==2 and not worker._pending
    assert all(packet.fps>=0 for packet in packets)


def test_one_failed_source_does_not_stop_the_other(worker,app):
    bad=selection('bad','stream','rtsp://127.0.0.1:10001/bad');good=selection('good')
    FakeSource.failures[bad.spec.value]=100
    states=[];worker.state_changed.connect(lambda ident,state,message:states.append((ident,state)))
    worker.request_start((bad,good));received={}
    def done():
        received.update(worker.take_latest());return good.record.camera_id in received and (bad.record.camera_id,'error') in states
    wait(app,done)
    assert received[good.record.camera_id].detections
    assert (bad.record.camera_id,'reconnecting') in states
    assert good.record.camera_id in worker.source_ids


def test_individual_stop_keeps_other_camera_running(worker,app):
    a,b=selection('a'),selection('b');worker.request_start((a,b))
    wait(app,lambda:len(FakeDetector.created)==1 and len(set(FakeDetector.created[0].calls))==2)
    worker.request_stop(a.record.camera_id)
    wait(app,lambda:a.record.camera_id not in worker.source_ids)
    worker.take_latest();time.sleep(.03)
    packets=worker.take_latest()
    assert a.record.camera_id not in packets and b.record.camera_id in packets


def test_stop_then_restart_uses_fresh_session_and_retains_model(worker,app):
    camera=selection('a');worker.request_start((camera,));received={}
    wait(app,lambda:bool(received.update(worker.take_latest()) or received))
    first=received[camera.record.camera_id].session_id;model=worker.detector
    worker.request_stop();wait(app,lambda:not worker.is_monitoring)
    received={};worker.request_start((camera,));wait(app,lambda:bool(received.update(worker.take_latest()) or received))
    assert received[camera.record.camera_id].session_id!=first
    assert worker.detector is model and first in model.resets


def test_stream_reconnect_gets_fresh_tracker_session(worker,app):
    camera=selection('drop','stream','rtsp://127.0.0.1:10002/drop');states=[]
    worker.state_changed.connect(lambda ident,state,message:states.append(state))
    worker.request_start((camera,));wait(app,lambda:'reconnecting' in states)
    wait(app,lambda:len(set(worker.detector.calls))>=2)
    assert len(set(worker.detector.calls))>=2


def test_selection_validation_and_command_bound(worker):
    with pytest.raises(ValueError):worker.request_start(())
    with pytest.raises(ValueError):worker.request_start(tuple(selection(str(i)) for i in range(9)))
    a=selection('a')
    with pytest.raises(ValueError):worker.request_start((a,a))
    same1=selection('a','stream','rtsp://a:secret@localhost/cam')
    same2=selection('b','stream','rtsp://b:other@localhost/cam')
    with pytest.raises(ValueError,match='same network'):worker.request_start((same1,same2))
    for _ in range(100):worker.request_stop('not-open')
    assert worker._commands.qsize()<=16


def test_configuration_is_validated_without_starting_capture(worker):
    for values in ({'confidence':float('nan')},{'image_size':12},{'hazards_enabled':'yes'},{'hazard_settings':{}}):
        with pytest.raises(ValueError):worker.set_options(**values)
    assert not FakeSource.created


def test_eof_is_inactive_and_all_capture_resources_release(worker,app):
    camera=selection('eof');states=[];worker.state_changed.connect(lambda ident,state,message:states.append(state))
    worker.request_start((camera,));wait(app,lambda:'eof' in states)
    wait(app,lambda:not worker.is_monitoring)
    assert all(source.closed for source in FakeSource.created)
    assert not worker.take_latest()

@pytest.mark.parametrize('count',[1,2,4,8])
def test_supported_camera_count_combinations_remain_fair(worker,app,count):
    sources=tuple(selection(str(i)) for i in range(count));received={}
    worker.request_start(sources)
    def all_received():received.update(worker.take_latest());return len(received)==count
    wait(app,all_received)
    assert len(FakeDetector.created)==1
    assert set(received)=={source.record.camera_id for source in sources}
    assert len({packet.session_id for packet in received.values()})==count
    assert len(worker._latest)<=count


def test_group_reselection_retains_unchanged_camera_session(worker,app):
    a,b,c=selection('a'),selection('b'),selection('c');worker.request_start((a,b));received={}
    def both():received.update(worker.take_latest());return len(received)==2
    wait(app,both);b_session=received[b.record.camera_id].session_id;worker.take_latest()
    worker.request_start((b,c));received={}
    def replacement():
        received.update(worker.take_latest())
        return b.record.camera_id in received and c.record.camera_id in received and a.record.camera_id not in worker.source_ids
    wait(app,replacement)
    assert received[b.record.camera_id].session_id==b_session
    assert len(FakeDetector.created)==1


def test_duplicate_exact_local_camera_is_rejected(worker):
    a=SimpleNamespace(record=SimpleNamespace(camera_id=str(uuid4()),name='Mac'),spec=SourceSpec('camera',0,camera_device_id='aabb',camera_name='Exact Mac'))
    b=SimpleNamespace(record=SimpleNamespace(camera_id=str(uuid4()),name='Alias'),spec=SourceSpec('camera',1,camera_device_id='aabb',camera_name='Same exact camera'))
    with pytest.raises(ValueError,match='same local'):worker.request_start((a,b))
    assert not FakeSource.created


def test_hazard_models_and_consumer_are_shared_but_source_ids_are_separate(app):
    from dataclasses import replace
    from sentinal.core.v02_settings import V02Settings
    from sentinal.vision.specialized import HazardObservation
    class FakeSuite:
        instances=[]
        def __init__(self,**kwargs):self.configure(**kwargs);self.calls=[];self.instances.append(self)
        def configure(self,**kwargs):self.options=kwargs;self.health={'fire_smoke':{'status':'active','device':'cpu'}}
        def infer(self,frame,frame_index=0,source_time_s=0,source_id='default'):
            self.calls.append(source_id);return (HazardObservation('fire',.7,(1,1,20,20),None,'synthetic','1','fire_smoke'),)
        def reset_tracking(self,source_id=None):pass
        def close(self):pass
    owner=MultiCameraWorker(AppConfig(),source_factory=FakeSource,detector_factory=FakeDetector,suite_factory=FakeSuite)
    owner.set_options(hazards_enabled=True,hazard_settings=replace(V02Settings(),detectors=('fire_smoke',),sample_interval_s=.05))
    seen=[];owner.set_incident_consumer(lambda packet,source_id:seen.append((packet,source_id)))
    a,b=selection('a'),selection('b');owner.start()
    try:
        owner.request_start((a,b));wait(app,lambda:len({ident for packet,ident in seen})==2)
        assert len(FakeSuite.instances)==1
        assert FakeSuite.instances[0].options['confidence']==.25
        assert len(set(FakeSuite.instances[0].calls))==2
        assert {ident for packet,ident in seen}=={a.record.camera_id,b.record.camera_id}
        assert all(packet.hazard_sampled and packet.hazards for packet,ident in seen)
    finally:owner.request_shutdown();assert owner.wait(5000)


def test_object_model_change_requires_an_inactive_wall(worker,app):
    worker.set_options(model_path='models/yolov8n-oiv7.pt')
    assert worker.config.model_path=='models/yolov8n-oiv7.pt'
    camera=selection('a');worker.request_start((camera,))
    wait(app,lambda:worker.detector is not None)
    assert worker.detector.config.model_path=='models/yolov8n-oiv7.pt'
    with pytest.raises(ValueError,match='Stop'):worker.set_options(model_path='models/yolo11n.pt')
    # Keeping the same selected path while active is harmless.
    worker.set_options(model_path='models/yolov8n-oiv7.pt')


@pytest.mark.parametrize('alias',[False,True])
def test_restart_waits_until_previous_capture_releases(app,alias):
    """A blocked close must reserve its device even with seven spare slots."""
    import threading
    release=threading.Event();closing=threading.Event();created=[]
    class SlowClose(FakeSource):
        def __init__(self,*args):super().__init__(*args);created.append(self)
        def close(self):
            if len(created)==1:
                closing.set();release.wait(3)
            super().close()
    owner=MultiCameraWorker(AppConfig(),source_factory=SlowClose,detector_factory=FakeDetector)
    source=selection('rapid','stream','rtsp://127.0.0.1:10003/rapid')
    replacement=selection('alias','stream',source.spec.value) if alias else source
    states=[];owner.state_changed.connect(lambda ident,state,message:states.append((ident,state)))
    owner.start()
    try:
        owner.request_start((source,));first={}
        wait(app,lambda:bool(first.update(owner.take_latest()) or first))
        session=first[source.record.camera_id].session_id;model=owner.detector
        owner.request_stop(source.record.camera_id);wait(app,closing.is_set)
        owner.request_start((replacement,));wait(app,lambda:replacement.record.camera_id in owner._pending)
        for _ in range(20):app.processEvents();time.sleep(.005)
        assert len(created)==1,'No replacement capture may open before old close completes'
        assert source.record.camera_id not in owner.source_ids and owner.is_monitoring
        release.set();fresh={}
        wait(app,lambda:bool(fresh.update(owner.take_latest()) or fresh))
        assert len(created)==2 and created[0].closed
        assert fresh[replacement.record.camera_id].session_id!=session and owner.detector is model
        app.processEvents()
        last_running=max(i for i,row in enumerate(states) if row==(replacement.record.camera_id,'running'))
        assert (replacement.record.camera_id,'stopped') not in states[last_running+1:]
    finally:
        release.set();owner.request_shutdown();assert owner.wait(5000)


def test_failed_capture_release_prevents_retry_and_camera_alias(app):
    created=[]
    class FailedClose(FakeSource):
        def __init__(self,*args):super().__init__(*args);created.append(self)
        def close(self):raise RuntimeError('Synthetic capture cleanup failure')
    owner=MultiCameraWorker(AppConfig(),source_factory=FailedClose,detector_factory=FakeDetector)
    source=selection('cleanup','stream','rtsp://127.0.0.1:10004/cleanup')
    states=[];owner.state_changed.connect(lambda ident,state,message:states.append((ident,state)))
    owner.start()
    try:
        owner.request_start((source,));wait(app,lambda:owner.detector is not None)
        owner.request_stop();wait(app,lambda:not owner.is_monitoring)
        for target in (source,selection('alias','stream',source.spec.value)):
            before=states.count((target.record.camera_id,'error'))
            owner.request_start((target,))
            wait(app,lambda:states.count((target.record.camera_id,'error'))>before and not owner.is_monitoring)
            assert len(created)==1,'A rejected retry must never construct another capture'
    finally:owner.request_shutdown();assert owner.wait(5000)


@pytest.mark.parametrize('category,expected',[('all',{'person','scissors','knife','spoon'}),('focus',{'person'}),('safety',{'scissors'})])
def test_category_filters_match_the_single_source_policy(app,category,expected):
    class CatalogDetector(FakeDetector):
        def infer(self,frame,confidence=None,source_id='default'):
            return tuple(Detection(i,label,.8,(1,1,30,40),i+1) for i,label in enumerate(('person','scissors','knife','spoon')))
    owner=MultiCameraWorker(AppConfig(),source_factory=FakeSource,detector_factory=CatalogDetector)
    owner.set_options(category_filter=category);owner.start();seen={}
    try:
        owner.request_start((selection('filter'),))
        wait(app,lambda:bool(seen.update(owner.take_latest()) or seen))
        packet=next(iter(seen.values()))
        assert {d.label for d in packet.detections}==expected
        assert packet.diagnostics['category_filter']==category
    finally:owner.request_shutdown();assert owner.wait(5000)


@pytest.mark.parametrize('value',['unknown',[],0])
def test_invalid_category_filter_does_not_start_capture(worker,value):
    with pytest.raises(ValueError,match='filter'):worker.set_options(category_filter=value)
    assert not FakeSource.created


def test_retiring_capture_cannot_disappear_when_it_finishes_during_reap(app):
    """An exit between polls must still undergo failed-release accounting."""
    owner=MultiCameraWorker(AppConfig());states=iter((True,False,False))
    camera=selection('failure','stream','rtsp://127.0.0.1:10005/failure')
    pump=SimpleNamespace(source_id=camera.record.camera_id,spec=camera.spec,resources_released=False,is_alive=lambda:next(states))
    owner._retiring=[pump]
    owner._reap();owner._reap()
    assert camera.record.camera_id in owner._blocked_sources
    assert not owner._retiring



def test_stream_does_not_reconnect_after_failed_capture_cleanup(app):
    created=[]
    class FailedReadAndClose(FakeSource):
        def __init__(self,*args):super().__init__(*args);created.append(self)
        def read(self):raise RuntimeError('Synthetic disconnected stream')
        def close(self):raise RuntimeError('Synthetic capture cleanup failure')
    owner=MultiCameraWorker(AppConfig(stream_reconnect_attempts=3,stream_reconnect_delay_s=.1),source_factory=FailedReadAndClose,detector_factory=FakeDetector)
    source=selection('badclose','stream','rtsp://127.0.0.1:10006/badclose');states=[]
    owner.state_changed.connect(lambda ident,state,message:states.append(state));owner.start()
    try:
        owner.request_start((source,));wait(app,lambda:'error' in states and not owner.is_monitoring)
        time.sleep(.15);app.processEvents()
        assert len(created)==1,'A failed cleanup must cancel all reconnect attempts'
        assert source.record.camera_id in owner._blocked_sources
    finally:owner.request_shutdown();assert owner.wait(5000)
