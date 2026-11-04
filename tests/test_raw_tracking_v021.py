"""Real ByteTrack/synthetic row contracts; these are not model accuracy tests."""
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from ultralytics.engine.results import Boxes
from sentinal.config import AppConfig
from sentinal.vision.raw_tracking import RawTrackerBank
from sentinal.vision.tracker import detections_from_result
from sentinal.vision.specialized import observations_from_result,SpecializedSuite
from sentinal.vision.model_registry import ASSETS
from sentinal.vision.detector import YOLODetector

FRAME=np.zeros((80,100,3),np.uint8)

def result(rows=(),name='knife'):
    return SimpleNamespace(boxes=Boxes(np.asarray(rows,dtype=np.float32).reshape(-1,6),FRAME.shape[:2]),names={0:name})

def test_new_unconfirmed_object_stays_visible_without_id_then_confirms():
    bank=RawTrackerBank();bank.associate(result(),FRAME)
    raw=result([(10,10,50,60,.85,0)])
    ids=bank.associate(raw,FRAME)
    assert ids=={},'A newly appearing second-frame track is not confirmed yet'
    observations=observations_from_result(raw,FRAME.shape,ASSETS['weapons'],.6,ids)
    assert len(observations)==1 and observations[0].track_id is None
    assigned=bank.associate(raw,FRAME)
    assert assigned.get(0) is not None
    assert observations_from_result(raw,FRAME.shape,ASSETS['weapons'],.6,assigned)[0].track_id==assigned[0]


def test_current_raw_coordinates_and_confidence_are_never_smoothed_or_replaced():
    bank=RawTrackerBank();first=result([(5,8,50,60,.85,0)])
    bank.associate(first,FRAME)
    second=result([(8,9,55,62,.81,0)])
    ids=bank.associate(second,FRAME)
    output=detections_from_result(second,FRAME.shape,.25,ids)
    assert output[0].bbox==(8.,9.,55.,62.)
    assert output[0].confidence==pytest.approx(.81)


def test_low_score_prediction_stays_visible_below_tracking_start_threshold():
    bank=RawTrackerBank();raw=result([(10,10,30,40,.18,0)])
    assert bank.associate(raw,FRAME)=={}
    assert len(detections_from_result(raw,FRAME.shape,.1,{}))==1


def test_camera_source_sessions_do_not_confirm_each_others_objects():
    bank=RawTrackerBank();bank.associate(result(),FRAME,'camera-A')
    raw=result([(10,10,50,60,.85,0)])
    assert bank.associate(raw,FRAME,'camera-A')=={}
    assert bank.associate(raw,FRAME,'camera-B').get(0) is not None
    assert bank.associate(raw,FRAME,'camera-A').get(0) is not None
    bank.reset('camera-A')
    assert bank.status('camera-A')=='idle' and bank.status('camera-B')=='active'


def test_tracker_pool_is_bounded_and_independent():
    bank=RawTrackerBank(max_sources=2)
    for name in ('A','B','C'):bank.associate(result(),FRAME,name)
    assert len(bank._trackers)==2 and 'A' not in bank._trackers


def test_tracker_failure_retains_predictions_and_exposes_unavailable(monkeypatch):
    bank=RawTrackerBank();raw=result([(10,10,40,50,.8,0)])
    monkeypatch.setattr(bank,'_tracker',lambda _:(_ for _ in ()).throw(RuntimeError('test tracker failure')))
    ids=bank.associate(raw,FRAME)
    assert ids=={} and bank.status()=='unavailable'
    assert len(detections_from_result(raw,FRAME.shape,.25,ids))==1
    bank.reset();assert bank.status()=='idle'


def test_malformed_raw_rows_cannot_poison_other_ids():
    bank=RawTrackerBank()
    raw=result([(10,10,40,50,.8,0),(1,1,float('nan'),50,.9,0),(5,5,5,8,.7,0)])
    assigned=bank.associate(raw,FRAME)
    assert set(assigned)=={0}


def test_category_thresholds_do_not_lower_every_other_category():
    raw=result([(10,10,40,50,.3,0)],name='fire')
    out=observations_from_result(raw,FRAME.shape,ASSETS['fire_smoke'],.6,{}, {'fire':.25})
    assert len(out)==1 and out[0].category=='fire'
    raw.names={0:'smoke'}
    assert observations_from_result(raw,FRAME.shape,ASSETS['fire_smoke'],.6,{}, {'fire':.25})==()


@pytest.mark.parametrize('mapping',[{'knife':.2},{'fire':float('nan')},{'fire':True},{'fire':.01}])
def test_invalid_per_category_thresholds_rejected(mapping):
    with pytest.raises(ValueError):SpecializedSuite(category_thresholds=mapping)


def test_base_detector_uses_predict_and_retains_unconfirmed_spoon(monkeypatch):
    calls=[];raw=result([(10,10,40,50,.8,0)],name='spoon')
    class Model:
        predictor=None
        def predict(self,**kwargs):calls.append(kwargs);return [raw]
    detector=YOLODetector(AppConfig(device='cpu'));detector.model=Model()
    detector._tracking.associate(result(),FRAME)
    out=detector.infer(FRAME)
    assert len(out)==1 and out[0].label=='spoon' and out[0].track_id is None
    assert calls[0]['mode']=='predict' and 'persist' not in calls[0]


def test_new_track_ids_remain_unique_when_other_model_trackers_are_created():
    first=RawTrackerBank();other=RawTrackerBank()
    initial=result([(2,2,20,25,.9,0)])
    assert first.associate(initial,FRAME,'camera-A')[0]==1
    other.associate(initial,FRAME,'different-model-camera-B')
    both=result([(2,2,20,25,.9,0),(60,30,95,75,.9,0)])
    first.associate(both,FRAME,'camera-A')
    other.associate(initial,FRAME,'new-camera-C')
    assigned=first.associate(both,FRAME,'camera-A')
    assert len(assigned)==2 and len(set(assigned.values()))==2
    assert assigned[0]==1 and assigned[1]>1
