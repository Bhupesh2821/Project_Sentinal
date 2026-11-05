"""Actual native dashboard + real detector + temporal alert + local review check.
Uses a specified licensed recorded fixture; never opens a physical camera.
--rtsp publishes that fixture to an authorized localhost-only RTSP service.
"""
from pathlib import Path
import argparse,json,sys,time,statistics,traceback
from dataclasses import replace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sentinal.application import prepare_runtime
from sentinal.config import AppConfig
from sentinal.core.v02_settings import V02Settings
from sentinal.core.incident_worker import IncidentWorker
from sentinal.interface.main_window import MainWindow
from sentinal.interface.themes import STYLESHEET


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',default='data/v02-demo/handgun_repeated_still.mp4')
    parser.add_argument('--category',default='weapon_handgun')
    parser.add_argument('--rtsp',action='store_true');parser.add_argument('--audio',action='store_true')
    parser.add_argument('--natural-motion',action='store_true',help='The selected fixture has verified genuine recorded motion')
    parser.add_argument('--persistence',type=float,default=.6,help='Explicit media-time confirmation threshold for this experiment')
    parser.add_argument('--output',default='docs/evidence/v02-2026-11-01/desktop-handgun.json')
    args=parser.parse_args();video=(ROOT/args.video).resolve();output=(ROOT/args.output).resolve()
    if not video.is_relative_to(ROOT) or not output.is_relative_to(ROOT):raise ValueError('Verification data must stay in project')
    output.parent.mkdir(parents=True,exist_ok=True)
    storage=ROOT/'work/v02-desktop'/output.stem;storage.mkdir(parents=True,exist_ok=True)
    if (storage/'incidents.sqlite3').exists():raise ValueError('Use a new output name to preserve previous evidence')
    report={'test':'Native actual SENTINAL camera/video → real inference → temporal incident → local alert → operator review',
        'source':str(video.relative_to(ROOT)),'transport':'localhost H264 RTSP' if args.rtsp else 'local file',
        'fixture_limitation':('Verified naturally moving recorded footage; one selected clip is not field accuracy validation.' if args.natural_motion else 'Repeated still clip. No claim of moving weapon tracking accuracy.'),
        'checks':{},'observed_transitions':[],'packets':[],'passed':False,'physical_cctv_tested':False,'camera_frames_saved':False}
    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QSoundEffect
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLESHEET)
    window=None;server=None;seen=set();first_observation_wall=None;first_alert_wall=None
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    def sample():
        nonlocal first_observation_wall
        if window is None:return
        packet=window.last_packet
        if packet is None or (packet.session_id,packet.frame_index) in seen:return
        seen.add((packet.session_id,packet.frame_index))
        hazards=[{'category':h.category,'confidence':h.confidence,'bbox':h.bbox,'track_id':h.track_id,'model_id':h.model_id,'model_version':h.model_version} for h in packet.hazards]
        if any(h['category']==args.category for h in hazards) and first_observation_wall is None:first_observation_wall=time.monotonic()
        report['packets'].append({'frame':packet.frame_index,'media_s':packet.source_time_s,'fps':packet.fps,'inference_ms':packet.inference_ms,'hazards':hazards,'health':packet.detector_health,'diagnostics':dict(packet.diagnostics)})
    def wait(predicate,timeout=90):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            app.processEvents();sample()
            if predicate():return
            time.sleep(.005)
        raise AssertionError('Native dashboard timed out: '+window.connection_label.text())
    def on_incident(row):
        nonlocal first_alert_wall
        report['observed_transitions'].append(dict(row))
        if row['category']==args.category and row['status']=='ALERTED' and first_alert_wall is None:first_alert_wall=time.monotonic()
    try:
        report['runtime_preparation']=prepare_runtime()
        with patch('sentinal.core.incident_worker.IncidentWorker',lambda parent=None:IncidentWorker(parent,storage/'incidents.sqlite3')):
            window=MainWindow(AppConfig());window.show();app.processEvents()
            check('launch_dark_interface',window.isVisible() and window.video_panel.isVisible())
            check('no_automatic_capture',window.worker.pipeline is None)
            check('privacy_defaults_off',not any(t.isChecked() for t in (window.metadata_toggle,window.incident_record_toggle,window.evidence_toggle,window.audio_toggle,window.desktop_toggle)))
            window.hazard_settings=replace(V02Settings(),confidence=.35,persistence_s=args.persistence,max_gap_s=2.,sample_interval_s=.2)
            window.hazards_toggle.setChecked(True)
        service=window._incident_worker;service.incident_changed.connect(on_incident)
        window.incident_record_toggle.setChecked(True);window.evidence_toggle.setChecked(True)
        if args.rtsp:
            from tools.verify_rtsp_v02 import LocalRTSP
            server=LocalRTSP(storage/'rtsp',video=video);server.start()
            window._use_network_stream(server.url,'','')
        else:window.load_video(video)
        window.start_button.click()
        wait(lambda:any(row['category']==args.category and row['status']=='ALERTED' for row in report['observed_transitions']) or window._state in ('eof','error'))
        check('real_target_reaches_temporal_alert',any(row['category']==args.category and row['status']=='ALERTED' for row in report['observed_transitions']))
        check('real_observations_have_pinned_provenance',any(h['category']==args.category and len(h['model_version'])>=7 for p in report['packets'] for h in p['hazards']))
        check('candidate_before_alert',any(row['category']==args.category and row['status']=='CANDIDATE' for row in report['observed_transitions']))
        check('uncertain_visual_alert',window.incident_banner.isVisible() and 'POSSIBLE' in window.incident_banner.text())
        wait(lambda:window.last_packet is not None and any(h.category==args.category for h in window.last_packet.hazards))
        check('actual_boxes_in_video_widget',any(h.category==args.category for h in window.video_panel._packet.hazards) and window.video_panel.show_boxes and window.video_panel.show_labels)
        check('native_live_screenshot',window.grab().save(str(output.with_suffix('.png'))))
        alert=next(row for row in report['observed_transitions'] if row['category']==args.category and row['status']=='ALERTED')
        ident=alert['incident_id'];report['alert_media_persistence_ms']=alert['alert_latency_ms']
        report['first_displayed_hazard_to_alert_wall_ms']=(first_alert_wall-first_observation_wall)*1000 if first_alert_wall and first_observation_wall else None
        wait(lambda:len(report['packets'])>=10)
        alerts=[row for row in report['observed_transitions'] if row['category']==args.category and row['status']=='ALERTED']
        check('duplicate_suppression',len(alerts)==len({row['incident_id'] for row in alerts}) and len(alerts)==len({(row['model_id'],row['track_id']) for row in alerts}))
        window.open_control_center();center=window._control_center;center.tabs.setCurrentIndex(1);center.refresh()
        wait(lambda:any(row['incident_id']==ident and row['status']=='ALERTED' for row in center.rows))
        index=next(i for i,row in enumerate(center.rows) if row['incident_id']==ident);center.table.selectRow(index);app.processEvents()
        center.note.setText('Authorized public fixture: human review integration test')
        center.review_buttons['ACKNOWLEDGED'].click()
        wait(lambda:any(row['incident_id']==ident and row['status']=='ACKNOWLEDGED' for row in center.rows))
        check('acknowledgment_in_actual_ui',True)
        index=next(i for i,row in enumerate(center.rows) if row['incident_id']==ident);center.table.selectRow(index);app.processEvents();center.review_buttons['DISMISSED'].click()
        wait(lambda:any(row['incident_id']==ident and row['status']=='DISMISSED' for row in center.rows))
        check('dismissal_in_actual_ui',True)
        check('incident_center_screenshot',center.grab().save(str(output.with_name(output.stem+'-incidents.png'))))
        center.tabs.setCurrentIndex(3);window._refresh_control_center(window.last_packet,force=True);app.processEvents()
        check('actual_measured_diagnostics','processing_fps' in center.diagnostics.toPlainText() and 'memory_rss_mb' in center.diagnostics.toPlainText())
        check('diagnostics_screenshot',center.grab().save(str(output.with_name(output.stem+'-diagnostics.png'))))
        center.hide()
        if args.audio:
            window.audio_toggle.setChecked(True)
            wait(lambda:window._alert_output.sound.status()==QSoundEffect.Status.Ready,15)
            window.test_sound_button.click();app.processEvents()
            check('sound_output_playing_state',window._alert_output.sound.isPlaying())
            wait(lambda:not window._alert_output.sound.isPlaying(),5)
            check('single_sound_ends',True)
            window.audio_toggle.setChecked(False)
            check('sound_can_be_disabled',not window._alert_output.audio_enabled)
            report['audio_scope']='Native sound effect Ready → playing → stopped; this verifies API output, not an observer hearing it.'
        started=time.monotonic();window.stop_button.click();wait(lambda:window._state=='stopped')
        report['stop_ms']=(time.monotonic()-started)*1000
        check('source_released',window.worker.pipeline.source is None)
        check('not_monitoring_after_stop','STOPPED' in window.status_chip.text())
        window.close();wait(lambda:not window.worker.isRunning() and not service.isRunning())
        check('workers_shutdown',True)
        from sentinal.storage.incident_database import IncidentDatabase
        from sentinal.storage.evidence_store import EvidenceStore
        db=IncidentDatabase(storage/'incidents.sqlite3');stored=db.get(ident)
        check('review_persisted_real_sqlite',stored['status']=='DISMISSED')
        entries=db.evidence(ident);check('opt_in_snapshot_saved',bool(entries))
        entry=entries[-1];check('snapshot_hash_valid',EvidenceStore(storage/'evidence').resolve(entry['path'],entry['sha256']).is_file())
        report['review_audit']=db.audit(ident);check('human_review_audited',len(report['review_audit'])>=3);db.close()
        warm=[p for p in report['packets'][2:] if p['inference_ms']>0]
        report['performance']={'displayed_packets':len(report['packets']),'mean_total_inference_ms':statistics.mean(p['inference_ms'] for p in warm),'mean_processing_fps':statistics.mean(p['fps'] for p in warm),'max_parent_rss_mb':max(p['diagnostics'].get('memory_rss_mb',0) for p in report['packets'])}
        report['passed']=all(report['checks'].values())
    except Exception as exc:
        report['failure']=str(exc);report['traceback']=traceback.format_exc()
    finally:
        if window is not None:
            window.close()
            end=time.monotonic()+40
            while time.monotonic()<end and (window.worker.isRunning() or (window._incident_worker is not None and window._incident_worker.isRunning())):
                app.processEvents();time.sleep(.01)
            window.worker.request_shutdown();window.worker.wait(5000)
            if window._incident_worker is not None:window._incident_worker.request_shutdown();window._incident_worker.wait(5000)
            app.processEvents()
        if server is not None:server.close()
        output.write_text(json.dumps(report,indent=2,default=str)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k not in {'packets','review_audit','observed_transitions'}},indent=2))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
