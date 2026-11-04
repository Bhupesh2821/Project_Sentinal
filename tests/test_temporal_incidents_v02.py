"""Synthetic engine contracts; these are not model-accuracy evidence."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from sentinal.core.incidents import Incident,TemporalEventEngine,TemporalRule
from sentinal.core.v02_settings import V02Settings

BASE=datetime.now(timezone.utc)
def stamp(t=0):return (BASE+timedelta(seconds=t)).isoformat()
def observation(category='weapon_firearm',score=.85,bbox=(1,2,25,30),track=3,model='unit-model',version='1'):
    return SimpleNamespace(category=category,confidence=score,bbox=bbox,track_id=track,model_id=model,model_version=version)
def engine(**kwargs):return TemporalEventEngine(TemporalRule(min_consecutive=3,persistence_s=.4,max_gap_s=.5,cooldown_s=2,**kwargs))
def sample(e,t,items=None,source='cam-01',session='session-a'):
    return e.process(source,session,(observation(),) if items is None else items,stamp(t),t)

def test_true_consecutive_samples_persist_and_emit_one_alert():
    e=engine();rows=[]
    for t in (0,.2,.4,.6,.8):rows.extend(sample(e,t))
    assert [r.status for r in rows]==['OBSERVED','CANDIDATE','ALERTED']
    alert=rows[-1]
    assert alert.alert_latency_ms==pytest.approx(400)
    assert alert.title=='POSSIBLE FIREARM'
    assert len({r.incident_id for r in rows})==1
    assert alert.confidence==.85 and alert.severity==3

def test_duplicate_media_time_does_not_count_as_fresh_frame():
    e=engine()
    assert sample(e,0)[0].status=='OBSERVED'
    assert sample(e,0)==()
    assert [r.status for r in sample(e,.4)]==['CANDIDATE']
    assert [r.status for r in sample(e,.5)]==['ALERTED']

@pytest.mark.parametrize('missed', [(),(observation(score=.2),)])
def test_missed_or_below_threshold_sample_breaks_consecutive_hits(missed):
    e=engine();first=sample(e,0)[0]
    assert sample(e,.2,missed)==()
    new=sample(e,.4)[0]
    assert new.status=='OBSERVED' and new.incident_id!=first.incident_id
    assert not any(r.status=='ALERTED' for r in sample(e,.6))
    assert sample(e,.8)[0].status=='ALERTED'

def test_excessive_gap_source_session_and_seek_reset_state():
    e=engine();first=sample(e,0)[0]
    assert sample(e,.6)[0].incident_id!=first.incident_id
    assert sample(e,.8,session='session-b')[0].status=='OBSERVED'
    assert sample(e,0,session='session-b')[0].status=='OBSERVED'
    assert sample(e,.2,source='cam-02')[0].status=='OBSERVED'
    assert not any(r.status=='ALERTED' for r in sample(e,.3,source='cam-01',session='session-b'))

def test_exact_tracking_identity_can_move_without_box_overlap():
    e=engine();sample(e,0)
    assert sample(e,.2,(observation(bbox=(100,2,124,30)),))[0].status=='CANDIDATE'
    assert sample(e,.4,(observation(bbox=(200,2,224,30)),))[0].status=='ALERTED'

def test_multiple_tracks_not_merged_and_duplicate_boxes_not_double_counted():
    e=engine()
    items=(observation(),observation(track=4,bbox=(40,2,65,30)))
    assert len(sample(e,0,items))==2
    assert len(sample(e,.2,items))==2
    assert len(sample(e,.4,items))==2
    other=engine()
    duplicate=(observation(),observation())
    assert len(sample(other,0,duplicate))==1
    assert [r.status for r in sample(other,.2,duplicate)]==['CANDIDATE']

def test_model_version_and_class_provenance_do_not_share_temporal_hits():
    e=engine();first=sample(e,0)[0]
    for t,obs in [(.2,observation(version='2')),(.4,observation(category='fire')),(.6,observation(model='other'))]:
        row=sample(e,t,(obs,))[0]
        assert row.status=='OBSERVED' and row.incident_id!=first.incident_id

def test_cooldown_suppresses_reappearance_then_expires():
    e=engine()
    for t in (0,.2,.4):sample(e,t)
    assert sample(e,1.1,())==()
    assert sample(e,1.2)==()
    assert sample(e,2.5)[0].status=='OBSERVED'

def test_camera_specific_rule_and_distinct_severity():
    rule=TemporalRule(confidence_threshold=.9,min_consecutive=2,persistence_s=.1,severity=1)
    e=TemporalEventEngine(camera_rules={'low-priority':rule})
    assert sample(e,0,source='low-priority')==()
    high=(observation(score=.95),)
    sample(e,.2,high,source='low-priority')
    alert=sample(e,.4,high,source='low-priority')[-1]
    assert alert.status=='ALERTED' and alert.severity==1 and alert.confidence==.95

@pytest.mark.parametrize('bad', [float('nan'),float('inf'),-1,True])
def test_invalid_media_timestamps_are_rejected(bad):
    with pytest.raises(ValueError):engine().process('cam','session',(observation(),),stamp(),bad)

@pytest.mark.parametrize('changes',[{'category':'untrained-gun'},{'confidence':float('nan')},{'bbox':(1,2,1,20)},{'track_id':-1},{'model_version':''}])
def test_invalid_observations_never_create_incidents(changes):
    obs=observation();obs.__dict__.update(changes)
    assert sample(engine(),0,(obs,))==()

def test_track_and_source_maps_are_bounded():
    e=TemporalEventEngine(max_tracks=8)
    for i in range(20):sample(e,0,source='camera-'+str(i))
    assert len(e._tracks)<=8 and len(e._sessions)<=8 and len(e._last_time)<=8

def test_incident_rejects_naive_or_reversed_times():
    row=sample(engine(),0)[0]
    for values in [{'last_seen':'2020-01-01T00:00:00+00:00'},{'first_seen':'2026-01-01T00:00:00'},{'alerted_at':'2020-01-01T00:00:00+00:00'}]:
        with pytest.raises(ValueError):replace(row,**values)

@pytest.mark.parametrize('values',[{'audio_severity':5},{'detect_fire':1},{'detect_smoke':'yes'},{'confidence':float('nan')},{'detectors':['weapons','weapons']},{'camera_rules':{'cam':{'min_consecutive':1}}}])
def test_settings_reject_invalid_options(values):
    with pytest.raises(ValueError):V02Settings(**values)

def test_settings_round_trip_and_recording_stays_runtime_only(tmp_path):
    settings=V02Settings(detect_fire=False,camera_rules={'cam':{'severity':1}})
    path=tmp_path/'v02.json';settings.save(path)
    assert V02Settings.load(path)==settings
    assert 'record' not in path.read_text() and settings.detectors==('weapons','fire_smoke')


@pytest.mark.parametrize('field',['confidence','persistence_s','audio_volume'])
def test_huge_json_integer_is_invalid_without_overflow(field):
    with pytest.raises(ValueError):V02Settings(**{field:10**1000})
    with pytest.raises(ValueError):TemporalRule(confidence_threshold=10**1000)
