"""Actual application entry point and demo preset; no capture is started."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel
from sentinal import application, __version__
from sentinal.interface import main_window

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',default='docs/evidence/v021-2026-11-03/launcher.json')
args=parser.parse_args()
original=main_window.MainWindow
report={'test':'Actual application.main demo startup / safe defaults','checks':{},'passed':False}

def build(*args,**kwargs):
    window=original(*args,**kwargs)
    def inspect():
        checks=report['checks']
        checks['visible_native_window']=window.isVisible()
        checks['bundled_video_preselected']=window.video_path==str(ROOT/'data/v02-demo/weapon_range_motion.mp4')
        checks['hazard_analysis_selected']=window.hazards_toggle.isChecked()
        checks['no_automatic_capture']=window.worker.pipeline is None and window._state=='idle'
        checks['recording_evidence_audio_desktop_off']=not any(t.isChecked() for t in (window.metadata_toggle,window.incident_record_toggle,window.evidence_toggle,window.audio_toggle,window.desktop_toggle))
        checks['demo_thresholds_explicit']=window.hazard_settings.confidence==.35 and window.hazard_settings.persistence_s==.3 and window.hazard_settings.max_gap_s==2. and window.hazard_settings.detectors==('weapons',)
        checks['version_displayed']=any(('V'+__version__) in label.text() for label in window.findChildren(QLabel,'edition'))
        window.close()
    QTimer.singleShot(400,inspect)
    return window

main_window.MainWindow=build
status=application.main(['--demo'])
report['checks']['application_clean_exit']=status==0
report['passed']=all(report['checks'].values())
output=(ROOT/args.output).resolve()
if not output.is_relative_to(ROOT):raise ValueError('Evidence must remain in project')
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
raise SystemExit(0 if report['passed'] else 1)
