"""Boundary/security tests use synthetic model rows; not accuracy evidence."""
from types import SimpleNamespace as NS
import math
import numpy as np
import pytest
from sentinal.vision.specialized import HazardObservation,SpecializedSuite,observations_from_result
from sentinal.vision.model_registry import ASSETS,verify_asset


def rows(coords=((1,2,20,30),),scores=(.8,),classes=(0,),ids=(7,),names=None):
    return NS(names=names or {0:'pistol'},boxes=NS(xyxy=coords,conf=scores,cls=classes,id=ids))


def test_source_pixels_clipped_with_provenance():
    out=observations_from_result(rows(coords=((-4,2,100,90),)),(50,80,3),ASSETS['weapons'],.6)
    assert out[0].bbox==(0.,2.,80,50)
    assert out[0].category=='weapon_handgun' and out[0].track_id==7
    assert out[0].model_version==ASSETS['weapons'].version


@pytest.mark.parametrize('box',[(1,2,float('nan'),30),(1,2,float('inf'),30),(5,2,4,30),(1,2,1,3)])
def test_invalid_boxes_cannot_become_valid_after_clipping(box):
    assert observations_from_result(rows(coords=(box,)),(50,80,3),ASSETS['weapons'],.6)==()


def test_unsupported_class_not_renamed_to_firearm():
    assert observations_from_result(rows(names={0:'0'}),(50,80,3),ASSETS['weapons'],.6)==()
    assert observations_from_result(rows(names={0:'person'}),(50,80,3),ASSETS['weapons'],.6)==()
    assert observations_from_result(rows(names={0:'grenade'}),(50,80,3),ASSETS['weapons'],.6)==()


def test_mixed_detector_class_is_ignored():
    assert observations_from_result(rows(names={0:'smoke'}),(50,80,3),ASSETS['weapons'],.6)==()
    assert observations_from_result(rows(),(50,80,3),ASSETS['fire_smoke'],.6)==()


def test_unassigned_tracking_id_retained_as_unknown():
    out=observations_from_result(rows(ids=None),(50,80,3),ASSETS['weapons'],.6)
    assert out[0].track_id is None


def test_array_mismatch_fails_closed():
    with pytest.raises(ValueError):observations_from_result(rows(scores=()),(50,80,3),ASSETS['weapons'],.6)


@pytest.mark.parametrize('confidence',[float('nan'),-1,1.2])
def test_invalid_confidence_rejected(confidence):
    with pytest.raises(ValueError):HazardObservation('fire',confidence,(1,2,3,4),None,'test','1','fire_smoke')


def test_missing_model_becomes_unavailable_without_random_results(monkeypatch):
    suite=SpecializedSuite(device='cpu',enabled=('weapons',))
    def fail(_):raise ValueError('Local detector weights are unavailable')
    monkeypatch.setattr(suite,'_load',fail)
    assert suite.infer(np.zeros((20,30,3),np.uint8))==()
    assert suite.health['weapons']['status']=='unavailable'


def test_fire_smoke_independent_controls_skip_disabled_model(monkeypatch):
    suite=SpecializedSuite(device='cpu',enabled=('fire_smoke',),detect_fire=False,detect_smoke=False)
    def unexpected(_):raise AssertionError('Disabled detector loaded')
    monkeypatch.setattr(suite,'_load',unexpected)
    assert suite.infer(np.zeros((20,30,3),np.uint8))==()
    assert suite.health['fire_smoke']['status']=='disabled'


def test_checksum_mismatch_prevents_deserialization(tmp_path):
    path=tmp_path/'bad.pt';path.write_bytes(b'not a model')
    with pytest.raises(ValueError,match='checksum'):verify_asset(NS(path=path,sha256='0'*64))


def test_unreviewed_pickle_global_is_rejected_before_execution(tmp_path):
    import torch,hashlib
    from pathlib import Path
    from sentinal.vision.safe_weights import load_pinned_yolo
    path=tmp_path/'unreviewed.pt';torch.save({'unreviewed':Path('data')},path)
    asset=NS(path=path,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),key='weapons')
    with pytest.raises(ValueError,match='unreviewed serialization class'):load_pinned_yolo(asset)


def test_legacy_dill_shim_only_allows_known_set():
    from sentinal.vision.safe_weights import _legacy_set
    assert _legacy_set('set') is set
    with pytest.raises(ValueError):_legacy_set('eval')
