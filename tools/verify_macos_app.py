"""Actual LaunchServices app -> real recorded-video inference -> Stop -> normal Quit."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT=ROOT/'docs/evidence/v031-2026-11-04/native-app.json'


def spawn_probe(output):
    """A real spawn child must import this module without opening another GUI."""
    Path(output).write_text(json.dumps({'pid':os.getpid(),'executable':sys.executable,
        'qt_application_imported':'PySide6.QtWidgets' in sys.modules})+'\n')


def run_inside_bundle(output):
    from PySide6.QtCore import QTimer,QCameraPermission,QThread,Qt
    from PySide6.QtWidgets import QApplication
    from sentinal import application,__version__
    from sentinal.interface import main_window
    target=Path(output).resolve()
    if not target.is_relative_to(ROOT):raise ValueError('App evidence must remain inside the project')
    target.parent.mkdir(parents=True,exist_ok=True)
    bundle=Path(os.environ['SENTINAL_APP_BUNDLE'])
    info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
    report={'test':'Actual macOS native app and genuine recorded-video detection',
        'pid':os.getpid(),'bundle':str(bundle.relative_to(ROOT)),'version':__version__,
        'project_linked':True,'standalone':False,'camera_opened':False,'inference_mocked':False,
        'fixture':'data/v02-demo/weapon_range_motion.mp4','checks':{},'passed':False}
    def save():target.write_text(json.dumps(report,indent=2)+'\n')
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    import multiprocessing
    from uuid import uuid4
    probe=ROOT/'work/mac-app-build'/('spawn-'+uuid4().hex+'.json')
    child=multiprocessing.get_context('spawn').Process(target=spawn_probe,args=(str(probe),))
    child.start();child.join(timeout=10)
    if child.is_alive():
        child.terminate();child.join(timeout=3)
        raise RuntimeError('Owned verification child did not return; no source was opened')
    result=json.loads(probe.read_text()) if probe.exists() else {}
    check('actual_spawn_child_uses_venv_without_recursive_gui',child.exitcode==0 and result.get('pid')!=os.getpid() and result.get('executable')==str(ROOT/'.venv/bin/python') and result.get('qt_application_imported') is False)
    probe.unlink(missing_ok=True)
    original=main_window.MainWindow
    def build(*args,**kwargs):
        window=original(*args,**kwargs);timer=QTimer(window);timer.setInterval(40)
        state={'started':False,'alert':None,'stopping':False};deadline=time.monotonic()+80
        def observe(row):
            if row.get('category')=='weapon_handgun' and row.get('status')=='ALERTED':state['alert']=dict(row)
        def tick():
            try:
                if time.monotonic()>deadline:raise AssertionError('Real app did not complete public-video inference and Stop within80seconds')
                if not state['started']:
                    check('native_cocoa_window_visible',window.isVisible() and QApplication.platformName()=='cocoa')
                    check('app_identity',QApplication.applicationName()=='SENTINAL' and info['CFBundleName']=='SENTINAL')
                    check('app_version_matches_source',info['CFBundleShortVersionString']==__version__)
                    check('camera_usage_description_present',bool(info.get('NSCameraUsageDescription')))
                    permission=QApplication.instance().checkPermission(QCameraPermission())
                    report['macos_camera_permission_state']=permission.name
                    report['camera_permission_requested']=False
                    check('camera_permission_state_queried_on_gui_thread',QThread.currentThread()==QApplication.instance().thread() and permission in (Qt.PermissionStatus.Granted,Qt.PermissionStatus.Denied,Qt.PermissionStatus.Undetermined))
                    check('real_venv_python_for_child_processes',sys.executable==str(ROOT/'.venv/bin/python'))
                    check('capture_waited_for_explicit_start',window.worker.pipeline is None)
                    check('real_motion_fixture_selected',window.video_path==str(ROOT/'data/v02-demo/weapon_range_motion.mp4'))
                    check('recording_audio_evidence_off',not any(t.isChecked() for t in (window.metadata_toggle,window.incident_record_toggle,window.evidence_toggle,window.audio_toggle,window.desktop_toggle)))
                    check('network_delivery_off',window._edge_bridge is None or not window._edge_bridge.is_enabled)
                    window._incident_worker.incident_changed.connect(observe)
                    state['started']=True;window.start_button.click();save()
                elif state['stopping']:
                    if window._state=='stopped':
                        check('video_resource_released',window.worker.pipeline.source is None)
                        check('monitoring_stopped','STOPPED' in window.status_chip.text())
                        check('recording_stayed_off',not window._incident_worker.persist)
                        report['ready_for_normal_quit']=True;timer.stop();save()
                elif state['alert'] is not None:
                    packet=window.last_packet
                    if packet is None or not any(h.category=='weapon_handgun' for h in packet.hazards):return
                    check('real_specialized_model',packet.detector_health['weapons']['model_id']=='GingerBrains/YOLOv8s-weapons')
                    check('actual_possible_alert_visible','POSSIBLE' in window.incident_banner.text())
                    check('genuine_weapon_box_in_video_panel',any(h.category=='weapon_handgun' for h in window.video_panel._packet.hazards))
                    check('labels_and_scores_enabled',window.video_panel.show_labels and window.video_panel.show_boxes)
                    image=window.video_panel.grab();check('native_video_rendered',not image.isNull())
                    check('public_fixture_frame_saved',image.save(str(target.with_name('native-app-video.png'))))
                    report['model_version']=packet.detector_health['weapons']['model_version']
                    report['actual_confidence']=state['alert']['confidence'];report['frame_index']=packet.frame_index
                    state['stopping']=True;window.stop_button.click()
                elif window._state in {'eof','error'}:raise AssertionError('Recorded source ended before a real possible-handgun alert')
            except Exception as exc:
                report['failure']=str(exc);timer.stop();save();window.close()
        timer.timeout.connect(tick);QTimer.singleShot(400,timer.start)
        return window
    main_window.MainWindow=build
    try:status=application.main(['--demo'])
    finally:main_window.MainWindow=original
    report['checks']['normal_application_exit']=status==0
    report['passed']=not report.get('failure') and bool(report.get('ready_for_normal_quit')) and all(report['checks'].values())
    save();return 0 if report['passed'] else 1


def verify(app,output):
    app=Path(app).resolve();output=Path(output).resolve()
    if not app.is_relative_to(ROOT) or not output.is_relative_to(ROOT):raise ValueError('App and evidence must remain in this project')
    if output.exists():raise ValueError('Choose a fresh evidence filename; prior verification must be preserved')
    output.parent.mkdir(parents=True,exist_ok=True)
    process=subprocess.Popen(['/usr/bin/open','-n','-W',str(app),'--args','--sentinal-verify',str(output)],cwd=ROOT)
    deadline=time.monotonic()+105;quit_sent=False;report=None
    while time.monotonic()<deadline:
        if output.exists():
            try:report=json.loads(output.read_text())
            except json.JSONDecodeError:pass
            if report and report.get('ready_for_normal_quit') and not quit_sent:
                # This is a normal application Quit event, not a forced process kill.
                code="ObjC.import('AppKit'); var app=$.NSRunningApplication.runningApplicationWithProcessIdentifier("+str(report['pid'])+"); if(!app) throw Error('App is unavailable'); app.terminate;"
                result=subprocess.run(['/usr/bin/osascript','-l','JavaScript','-e',code],capture_output=True,text=True,timeout=12)
                if result.returncode or result.stdout.strip()!='true':
                    raise RuntimeError('Normal macOS Quit request was not accepted; app remains stopped for inspection')
                quit_sent=True
            if report and (report.get('passed') or report.get('failure')) and process.poll() is not None:break
        if process.poll() is not None and not report:break
        time.sleep(.2)
    if process.poll() is None:raise RuntimeError('App did not exit normally within the verification deadline; no forced termination was used')
    if report is None:raise RuntimeError('App did not produce evidence; inspect logs/app-launcher.log')
    report=json.loads(output.read_text());report['checks']['launchservices_open_completed']=process.returncode==0
    report['checks']['macos_normal_quit_event_sent']=quit_sent
    report['passed']=report['passed'] and all(report['checks'].values())
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',default=str(ROOT/'dist/SENTINAL.app'))
    parser.add_argument('--output',default=str(DEFAULT_OUTPUT))
    args=parser.parse_args();raise SystemExit(verify(args.app,args.output))
