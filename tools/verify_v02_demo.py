"""Actual demo entry point, explicit Start, real moving-weapon alert and Stop."""
from pathlib import Path
import argparse,json,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QTimer
from sentinal import application
from sentinal.interface import main_window
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',default='docs/evidence/v021-2026-11-03/demo-entry.json')
args=parser.parse_args()
output=(ROOT/args.output).resolve()
if not output.is_relative_to(ROOT):raise ValueError('Evidence must remain in project')
output.parent.mkdir(parents=True,exist_ok=True)
original=main_window.MainWindow
report={'test':'Actual --demo entry → deliberate Start → moving-weapon real alert → Stop','checks':{},'passed':False}

def build(*args,**kwargs):
    window=original(*args,**kwargs);timer=QTimer(window);timer.setInterval(30)
    state={'started':False,'alert':None,'stopping':False};deadline=time.monotonic()+60
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    def observe(row):
        if row['category']=='weapon_handgun' and row['status']=='ALERTED':state['alert']=dict(row)
    def tick():
        try:
            if time.monotonic()>deadline:raise AssertionError('Demo did not reach its real alert and safe Stop within60seconds')
            if not state['started']:
                check('preset_waits_for_start',window.worker.pipeline is None)
                check('real_motion_fixture',window.video_path==str(ROOT/'data/v02-demo/weapon_range_motion.mp4'))
                check('recording_audio_evidence_off',not any(t.isChecked() for t in (window.incident_record_toggle,window.evidence_toggle,window.audio_toggle,window.desktop_toggle,window.metadata_toggle)))
                check('weapon_only_profile',window.hazard_settings.detectors==('weapons',) and window.hazard_settings.persistence_s==.3)
                window._incident_worker.incident_changed.connect(observe)
                state['started']=True;window.start_button.click()
            elif state['stopping']:
                if window._state=='stopped':
                    check('source_released',window.worker.pipeline.source is None)
                    check('monitoring_inactive','STOPPED' in window.status_chip.text())
                    timer.stop();window.close()
            elif state['alert'] is not None:
                packet=window.last_packet
                if packet is None or not any(h.category=='weapon_handgun' for h in packet.hazards):return
                check('real_final_model',packet.detector_health['weapons']['model_id']=='GingerBrains/YOLOv8s-weapons')
                check('uncertain_alert_visible','POSSIBLE' in window.incident_banner.text())
                check('actual_weapon_box_present',any(h.category=='weapon_handgun' for h in window.video_panel._packet.hazards))
                check('recording_remains_off',not window._incident_worker.persist)
                report['alert']=state['alert'];report['frame']=packet.frame_index
                report['checks']['public_demo_screenshot']=window.grab().save(str(output.with_suffix('.png')))
                state['stopping']=True;window.stop_button.click()
            elif window._state in {'eof','error'}:raise AssertionError('Demo ended without a temporally confirmed handgun')
        except Exception as exc:
            report['failure']=str(exc);timer.stop();window.close()
    timer.timeout.connect(tick);QTimer.singleShot(400,timer.start)
    return window

main_window.MainWindow=build
status=application.main(['--demo'])
report['checks']['clean_application_exit']=status==0
report['passed']=not report.get('failure') and all(report['checks'].values()) and 'alert' in report
output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2));raise SystemExit(0 if report['passed'] else 1)
