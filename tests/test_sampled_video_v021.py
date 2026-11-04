"""UI sampling keeps real boxes and pixels together; synthetic DTOs only."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
import numpy as np
from PySide6.QtWidgets import QApplication
from sentinal.interface.video_panel import VideoPanel
from sentinal.vision.specialized import HazardObservation


def test_unsampled_frame_does_not_erase_boxes_or_relocate_them(packet):
    app=QApplication.instance() or QApplication([]);panel=VideoPanel()
    fire=HazardObservation('fire',.8,(1,1,10,10),None,'test','1','fire_smoke')
    sampled=replace(packet,hazard_sampled=True,hazards=(fire,),detector_health={'fire_smoke':{'status':'active'}})
    assert panel.present_packet(sampled,True)
    newer=replace(sampled,frame=np.full_like(packet.frame,200),hazards=(),hazard_sampled=False,frame_index=2)
    assert not panel.present_packet(newer,True)
    assert panel._packet is sampled and panel._packet.frame is sampled.frame
    assert panel._sampled_view
    # A new analyzed empty sample clears previous hazard boxes immediately.
    clear=replace(newer,hazard_sampled=True,frame_index=3)
    assert panel.present_packet(clear,True) and panel._packet.hazards==()
    panel.close()


def test_disabled_or_failed_hazard_model_does_not_freeze_video(packet):
    app=QApplication.instance() or QApplication([]);panel=VideoPanel()
    sample=replace(packet,hazard_sampled=True,detector_health={'weapons':{'status':'active'}})
    panel.present_packet(sample,True)
    newer=replace(sample,hazard_sampled=False,frame_index=2)
    assert panel.present_packet(newer,False) and panel._packet is newer and not panel._sampled_view
    panel.present_packet(sample,True)
    failed=replace(newer,detector_health={'weapons':{'status':'unavailable'}})
    assert panel.present_packet(failed,True) and panel._packet is failed
    panel.close()


def test_source_switch_never_reuses_previous_camera_sample(packet):
    app=QApplication.instance() or QApplication([]);panel=VideoPanel()
    first=replace(packet,hazard_sampled=True,detector_health={'weapons':{'status':'active'}})
    panel.present_packet(first,True)
    other=replace(first,session_id='different-source',hazard_sampled=False)
    assert panel.present_packet(other,True) and panel._packet is other
    panel.clear_frame();assert panel._packet is None and not panel._sampled_view
    panel.close()
