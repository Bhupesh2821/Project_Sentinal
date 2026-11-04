"""Actual native camera wall: two loopback RTSP feeds -> real AI -> alerts/review.

Test storage is isolated under work/, using the real application workers, models,
SQLite and camera adapters. Public licensed stills repeated as video are an
integration fixture, not natural-motion or physical-CCTV accuracy evidence.
No physical camera opens, audio plays, external notifications or private media.
"""
from pathlib import Path
from datetime import datetime,timezone
from dataclasses import replace
import argparse,json,statistics,sys,time,traceback
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='docs/evidence/v021-2026-11-03/camera-wall-native.json')
    args=parser.parse_args();output=(ROOT/args.output).resolve()
    if not output.is_relative_to(ROOT):raise ValueError('Evidence must stay inside SENTINAL')
    output.parent.mkdir(parents=True,exist_ok=True)
    storage=ROOT/'work/camera-wall-native'/output.stem
    storage.mkdir(parents=True,exist_ok=True)
    if (storage/'incidents.sqlite3').exists():raise ValueError('Use a new output name to preserve previous evidence')
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from sentinal.application import prepare_runtime
    from sentinal.config import AppConfig
    from sentinal.core.incident_worker import IncidentWorker
    from sentinal.core.v02_settings import V02Settings
    from sentinal.interface.main_window import MainWindow
    from sentinal.interface.themes import STYLESHEET
    from sentinal.storage.camera_registry import CameraRegistry
    from sentinal.storage.video_library import VideoLibrary
    from sentinal.storage.incident_database import IncidentDatabase
    from tools.verify_rtsp_v02 import LocalRTSP
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLESHEET)
    started=time.monotonic();window=wall=service=None;feeds=[];seen=set();ids=();ticks=[]
    report={'test':'Native SENTINAL simultaneous camera wall to real pretrained inference, visual alert and human review',
        'created_utc':datetime.now(timezone.utc).isoformat(),'checks':{},'packets':[],'incidents':[],'states':[],'errors':[],
        'passed':False,'physical_cctv_tested':False,'physical_camera_activated':False,'inference_mocked':False,
        'fixture_scope':'Licensed real photos repeated as loopback H264 RTSP videos; integration-only, not natural-motion accuracy or toy/real discrimination.',
        'fixtures':['data/v02-demo/handgun_repeated_still.mp4','data/v02-demo/fire_repeated_still.mp4'],
        'test_isolation':'Only constructor defaults for settings/video-library/incident-database are redirected; inference, temporal reasoning, presentation, storage and review use actual implementations.',
        'private_footage_saved':False,'snapshot_recording':False,'audio_played':False,'external_notification_sent':False}
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    def sample():
        if wall is None:return
        for ident,tile in wall.tiles.items():
            packet=tile.last_packet
            if packet is None or (ident,packet.session_id,packet.frame_index) in seen:continue
            seen.add((ident,packet.session_id,packet.frame_index))
            report['packets'].append({'camera_id':ident,'session_id':packet.session_id,'frame':packet.frame_index,
                'timestamp':packet.timestamp,'source_time_s':packet.source_time_s,'hazard_sampled':packet.hazard_sampled,
                'processing_fps':packet.fps,'inference_ms':packet.inference_ms,
                'presented_frame':tile.video._packet.frame_index if tile.video._packet is not None else None,
                'frame_age_ms':packet.frame_age_ms,'dropped_frames':packet.dropped_frames,'diagnostics':packet.diagnostics,
                'hazards':[{'category':h.category,'confidence':h.confidence,'bbox':h.bbox,'track_id':h.track_id,'model_id':h.model_id,'model_version':h.model_version} for h in packet.hazards],
                'detector_health':packet.detector_health})
    def wait(predicate,timeout=45):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            app.processEvents();sample()
            if predicate():return
            time.sleep(.005)
        raise AssertionError('Native camera wall timed out: '+(wall.message.text() if wall is not None else 'before creation'))
    def count(ident):return sum(row['camera_id']==ident for row in report['packets'])
    def has_alert(ident,category):return any(row['source_id']==ident and row['category']==category and row['status']=='ALERTED' for row in report['incidents'])
    try:
        report['runtime_preparation']=prepare_runtime()
        for index,video in enumerate(report['fixtures']):
            feeds.append(LocalRTSP(storage/f'rtsp-{index}',ROOT/video).start())
        with patch('sentinal.interface.main_window.VideoLibrary',lambda:VideoLibrary(storage/'video-library')), \
             patch('sentinal.core.incident_worker.IncidentWorker',lambda parent=None:IncidentWorker(parent,storage/'incidents.sqlite3')), \
             patch.object(V02Settings,'load',classmethod(lambda cls:cls())):
            window=MainWindow(AppConfig());window.show();app.processEvents()
            check('main_native_interface_visible',window.isVisible() and window.video_panel.isVisible())
            check('no_automatic_single_source_capture',window.worker.pipeline is None)
            check('privacy_defaults_off',not any(t.isChecked() for t in (window.metadata_toggle,window.incident_record_toggle,window.evidence_toggle,window.audio_toggle,window.desktop_toggle)))
            registry=CameraRegistry(storage/'camera-registry/registry.sqlite3');window._camera_registry=registry
            records=[registry.upsert_network(name,feed.url) for name,feed in zip(('Authorized public weapon fixture','Authorized public fire fixture'),feeds)]
            ids=tuple(record.camera_id for record in records)
            window.open_camera_wall();wall=window._camera_wall;app.processEvents()
            wall.worker.state_changed.connect(lambda ident,state,message:report['states'].append({'camera_id':ident,'state':state,'elapsed_s':time.monotonic()-started}))
            wall.worker.error.connect(lambda ident,message:report['errors'].append({'camera_id':ident,'message':message}))
            check('native_camera_wall_visible_in_standby',wall.isVisible() and not wall.is_monitoring and not wall.tiles and wall.worker.detector is None)
            wall.set_selections(tuple(registry.resolve(ident) for ident in ids))
            check('selection_without_capture',not wall.is_monitoring and wall.worker.detector is None and not wall.worker.source_ids)
            window.hazard_settings=replace(V02Settings(),confidence=.35,display_confidence=.25,persistence_s=.4,max_gap_s=2.,sample_interval_s=.2)
            wall.hazards.setChecked(True);service=window._incident_worker
            service.incident_changed.connect(lambda row:report['incidents'].append(dict(row)))
            wall.record.setChecked(True)
            check('recording_explicit_and_snapshot_audio_off',wall.record.isChecked() and not wall.evidence.isChecked() and not window.audio_toggle.isChecked() and not window.desktop_toggle.isChecked())
        heartbeat=QTimer();heartbeat.setInterval(25);heartbeat.timeout.connect(lambda:ticks.append(time.monotonic()));heartbeat.start()
        wall.start_button.click();app.processEvents()
        check('explicit_multi_start_blocks_competing_single_capture',wall.is_monitoring and not window.start_button.isEnabled() and not window.model_combo.isEnabled() and window.worker.pipeline is None)
        wait(lambda:all(count(ident)>=8 for ident in ids))
        check('both_selected_streams_render_actual_frames',all(wall.tiles[ident].last_packet is not None and wall.tiles[ident].video._packet is not None and wall.tiles[ident].video._packet.session_id==wall.tiles[ident].last_packet.session_id and wall.tiles[ident].video._packet.frame_index<=wall.tiles[ident].last_packet.frame_index for ident in ids))
        check('independent_sessions',wall.tiles[ids[0]].last_packet.session_id!=wall.tiles[ids[1]].last_packet.session_id)
        wait(lambda:has_alert(ids[0],'weapon_handgun') and has_alert(ids[1],'fire'))
        check('real_outputs_reach_temporal_alerts_for_both_cameras',True)
        check('candidate_stages_for_both_cameras',all(any(row['source_id']==ident and row['status']=='CANDIDATE' for row in report['incidents']) for ident in ids))
        check('per_camera_alerts_visible',all(wall.tiles[ident].alert.isVisible() and 'POSSIBLE' in wall.tiles[ident].alert.text() and 'Awaiting' in wall.tiles[ident].alert.text() for ident in ids))
        check('wall_summary_has_visible_warning','POSSIBLE' in wall.alert_summary.text())
        check('real_pinned_models_active',all(all(wall.tiles[ident].last_packet.detector_health[key]['status']=='active' for key in ('weapons','fire_smoke')) for ident in ids))
        check('one_loaded_shared_model_set',wall.worker.detector.model is not None and all(wall.worker.hazard_suite._models[key]['model'] is not None for key in ('weapons','fire_smoke')))
        check('boxes_labels_ids_enabled',all(tile.video.show_boxes and tile.video.show_labels and tile.video.show_ids for tile in wall.tiles.values()))
        check('real_confidence_coordinates_and_tracking_available',all(any(row['camera_id']==ident and any(h['track_id'] is not None and 0<h['confidence']<=1 and h['bbox'][2]>h['bbox'][0] for h in row['hazards']) for row in report['packets']) for ident in ids))
        wait(lambda:all(registry.get(ident).last_frame_utc is not None for ident in ids))
        check('fresh_frame_health_is_online_active',all(registry.get(ident).connection_health=='online' and registry.get(ident).ai_status=='active' for ident in ids))
        wait(lambda:all(wall.tiles[ident].video._packet is not None and any(h.category==category for h in wall.tiles[ident].video._packet.hazards) for ident,category in zip(ids,('weapon_handgun','fire'))),15)
        check('actual_target_boxes_in_both_video_widgets',all(wall.tiles[ident].video._packet.hazards for ident in ids))
        check('sampled_view_displays_exact_analyzed_frame',all(wall.tiles[ident].video._sampled_view and wall.tiles[ident].video._packet.hazard_sampled for ident in ids))
        check('native_public_fixture_wall_screenshot',wall.grab().save(str(output.with_suffix('.png'))))
        check('qt_event_loop_stays_active',len(ticks)>=20)
        wall._open_incidents();center=window._control_center
        wait(lambda:len(center.rows)>=2)
        check('review_opens_actual_incident_tab',center.isVisible() and center.tabs.currentIndex()==1)
        target=next(row for row in report['incidents'] if row['source_id']==ids[0] and row['category']=='weapon_handgun' and row['status']=='ALERTED')
        target_id=target['incident_id']
        def choose():
            center.table.selectRow(next(i for i,row in enumerate(center.rows) if row['incident_id']==target_id));app.processEvents()
        wait(lambda:any(row['incident_id']==target_id for row in center.rows));choose()
        center.note.setText('Authorized licensed loopback fixture: multi-camera review verification')
        center.review_buttons['ACKNOWLEDGED'].click()
        wait(lambda:any(row['incident_id']==target_id and row['status']=='ACKNOWLEDGED' for row in center.rows))
        check('acknowledge_updates_camera_tile','ACKNOWLEDGED' in wall.tiles[ids[0]].alert.text())
        choose();center.review_buttons['DISMISSED'].click()
        wait(lambda:any(row['incident_id']==target_id and row['status']=='DISMISSED' for row in center.rows))
        check('dismiss_updates_camera_tile','DISMISSED' in wall.tiles[ids[0]].alert.text())
        check('unrelated_camera_warning_remains','POSSIBLE' in wall.tiles[ids[1]].alert.text())
        check('native_incident_review_screenshot',center.grab().save(str(output.with_name(output.stem+'-incidents.png'))))
        center.tabs.setCurrentIndex(3);window._refresh_control_center(force=True);app.processEvents()
        check('real_diagnostics_show_per_camera_processing','processing_fps' in center.diagnostics.toPlainText() and 'memory_rss_mb' in center.diagnostics.toPlainText())
        check('overview_has_fresh_two_camera_health',center.camera_table.rowCount()==2 and all(center.camera_table.item(i,2).text() for i in range(2)))
        center.hide();before=count(ids[1]);wall.tiles[ids[0]].stop_button.click()
        wait(lambda:wall.states.get(ids[0])=='stopped' and count(ids[1])>=before+4)
        check('individual_stop_only_releases_selected_camera',wall.tiles[ids[0]].last_packet is None and wall.states.get(ids[1])=='running' and wall.is_monitoring)
        stopping=time.monotonic();wall.stop_all.click();wait(lambda:not wall.is_monitoring)
        report['stop_all_ms']=(time.monotonic()-stopping)*1000
        wait(lambda:window.start_button.isEnabled() and window.model_combo.isEnabled())
        check('all_stop_clears_frames_and_reenables_single_start',all(tile.last_packet is None for tile in wall.tiles.values()))
        wall.close();wait(lambda:wall._closed and not wall.worker.isRunning())
        check('close_releases_selection_refs_and_all_captures',not wall._selected and not wall.worker.source_ids and not wall.worker._retiring)
        window.open_camera_wall();wall=window._camera_wall;app.processEvents()
        check('reopened_wall_standby_no_capture',wall.isVisible() and not wall.is_monitoring and not wall.tiles and wall.worker.detector is None)
        heartbeat.stop();window.close()
        wait(lambda:not window.isVisible() and not window.worker.isRunning() and not wall.worker.isRunning() and not service.isRunning())
        check('normal_app_shutdown_releases_workers',True)
        db=IncidentDatabase(storage/'incidents.sqlite3');stored=db.get(target_id)
        check('human_review_persists_real_sqlite',stored['status']=='DISMISSED')
        check('human_review_audit_saved',len(db.audit(target_id))>=3)
        check('snapshot_remains_disabled',not db.evidence(target_id));db.close()
        per_camera={}
        for ident in ids:
            warm=[row for row in report['packets'] if row['camera_id']==ident][2:]
            per_camera[ident]={'displayed_packets':count(ident),'mean_processing_fps':statistics.mean(row['processing_fps'] for row in warm),
                'mean_total_inference_ms':statistics.mean(row['inference_ms'] for row in warm),
                'hazard_sampled_packets':sum(row['hazard_sampled'] for row in warm),
                'mean_inference_ms_on_hazard_sampled_frames':statistics.mean(row['inference_ms'] for row in warm if row['hazard_sampled']),
                'max_parent_rss_mb':max(row['diagnostics'].get('memory_rss_mb',0) for row in warm)}
        report['performance']={'per_camera':per_camera,'qt_heartbeat_ticks':len(ticks),'max_qt_heartbeat_gap_ms':max((b-a)*1000 for a,b in zip(ticks,ticks[1:])) if len(ticks)>1 else None,
            'scope':'Short native integration observation. Processing FPS includes base-only frames; specialized analysis runs on configured samples and the video presents complete analyzed frames. Not sustained or physical-camera benchmark.'}
        report['passed']=all(report['checks'].values())
    except Exception as exc:
        report['failure']=str(exc);report['traceback']=traceback.format_exc()
    finally:
        if window is not None:
            window.close();deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                app.processEvents()
                threads=[window.worker]
                if window._camera_wall is not None:threads.append(window._camera_wall.worker)
                if window._incident_worker is not None:threads.append(window._incident_worker)
                if not any(thread.isRunning() for thread in threads):break
                time.sleep(.01)
            for thread in threads:thread.request_shutdown();thread.wait(5000)
            app.processEvents()
        for feed in feeds:feed.close()
        report['elapsed_s']=time.monotonic()-started
        output.write_text(json.dumps(report,indent=2,default=str)+'\n')
        print(json.dumps({key:value for key,value in report.items() if key not in {'packets','incidents','states'}},indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
