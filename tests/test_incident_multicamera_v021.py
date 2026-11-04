"""Bounded camera-fair alert intake. Synthetic packets test scheduling, not AI."""
from dataclasses import replace
from sentinal.core.incident_worker import IncidentWorker
from sentinal.core.v02_settings import V02Settings


def test_fast_camera_does_not_erase_other_camera_pending_sample(tmp_path, packet):
    worker=IncidentWorker(path=tmp_path/'unused.sqlite3')
    for source,index in [('slow',1),('fast',1),('fast',2),('fast',3)]:
        worker.submit_packet(replace(packet,hazard_sampled=True,frame_index=index),source)
    first=worker._take_packet();second=worker._take_packet()
    assert first[1]=='slow' and first[0].frame_index==1
    assert second[1]=='fast' and second[0].frame_index==3
    assert worker.dropped_samples==2 and worker._take_packet() is None
    assert worker._packet is None and not worker.path.exists()


def test_each_camera_latest_mailbox_is_bounded_to_eight_sources(tmp_path,packet):
    worker=IncidentWorker(path=tmp_path/'unused.sqlite3')
    for i in range(12):worker.submit_packet(replace(packet,hazard_sampled=True,frame_index=i),f'camera-{i}')
    assert len(worker._packets)==8 and worker.dropped_samples==4
    pending=[worker._take_packet() for _ in range(8)]
    assert [item[1] for item in pending]==[f'camera-{i}' for i in range(4,12)]
    assert worker._take_packet() is None


def test_box_display_score_and_alert_score_remain_independent():
    settings=V02Settings(display_confidence=.25,confidence=.6,category_thresholds={'fire':.2})
    worker=IncidentWorker();worker.settings=settings;engine=worker._engine()
    assert engine._rule('camera','fire').confidence_threshold==.6
    assert engine._rule('camera','weapon_knife').confidence_threshold==.6
    assert settings.display_confidence==.25 and settings.category_thresholds['fire']==.2
