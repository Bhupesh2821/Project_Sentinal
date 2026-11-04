"""Real recorded model inference -> temporal alert -> signed HTTP -> private review.

Uses actual implementations and the licensed moving range fixture; creates only
isolated project-local credentials/stores. No physical camera or Internet upload.
"""
from datetime import datetime,timezone
import argparse
from http.cookiejar import CookieJar
import hashlib
import json
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError,URLError
from urllib.request import Request,build_opener,HTTPCookieProcessor,ProxyHandler,HTTPSHandler
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sentinal.connected.edge import EdgeConfig
from sentinal.connected.monitor import parser as monitor_parser,run
from sentinal.connected.protocol import canonical_json
from sentinal.connected.server import build_server
from sentinal.connected.store import Store


def main(argv=None):
    args=argparse.ArgumentParser(description=__doc__)
    args.add_argument('--video',default='data/v02-demo/weapon_range_motion.mp4')
    args.add_argument('--detectors',choices=('weapons','fire_smoke','both'),default='weapons')
    args.add_argument('--category',default='weapon_handgun')
    args.add_argument('--https',action='store_true',help='Use an isolated project-local test certificate and verified client CA; no system trust changes')
    args.add_argument('--output',default='docs/evidence/v03-2026-11-03/edge-real-inference.json')
    options=args.parse_args(argv)
    output=(ROOT/options.output).resolve();video=(ROOT/options.video).resolve()
    if not output.is_relative_to(ROOT) or not video.is_relative_to(ROOT):raise ValueError('Verification assets stay inside project')
    output.parent.mkdir(parents=True,exist_ok=True)
    tag='edge-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+secrets.token_hex(3)
    work=ROOT/'work/v03-verification'/tag;work.mkdir(parents=True,exist_ok=False)
    report={'test':'Actual licensed recorded video -> real selected models -> temporal event -> signed outbound metadata -> authenticated API review',
        'created_at':datetime.now(timezone.utc).isoformat(),'fixture':str(video.relative_to(ROOT)),
        'fixture_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'physical_camera_tested':False,
        'base44_tested':False,'mobile_hardware_tested':False,'internet_upload':False,
        'inference_mocked':False,'images_saved':False,'https_tested':options.https,
        'fixture_scope':'Licensed real photograph repeated as video; integration only, not natural-motion acceptance' if 'repeated_still' in video.name else 'Selected recorded video; moving range fixture has genuine motion, without field-accuracy acceptance',
        'checks':{},'passed':False}
    store=Store(work/'backend/server.sqlite3');server=None;thread=None;hazard_times=set();preview_seen=False;observed_alert=[]
    password=secrets.token_urlsafe(24);secret=secrets.token_urlsafe(48)
    store.create_user('verification-operator',password,'operator')
    store.register_device('verification-edge','Authorized verification edge',secret)
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    try:
        cert=key=None
        if options.https:
            cert=work/'test-cert.pem';key=work/'test-key.pem';configfile=work/'test-openssl.conf'
            configfile.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=127.0.0.1\n[ext]\nsubjectAltName=IP:127.0.0.1\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\nextendedKeyUsage=serverAuth\n')
            subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-sha256','-days','1','-keyout',str(key),'-out',str(cert),'-config',str(configfile)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            key.chmod(0o600)
        server=build_server(store,port=0,allow_local_preview=True,tls_cert=str(cert) if cert else None,tls_key=str(key) if key else None)
        origin=f'{"https" if options.https else "http"}://127.0.0.1:{server.server_port}'
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        context=ssl.create_default_context(cafile=str(cert)) if cert else ssl.create_default_context()
        first=build_opener(ProxyHandler({}),HTTPSHandler(context=context),HTTPCookieProcessor(CookieJar()))
        second=build_opener(ProxyHandler({}),HTTPSHandler(context=context),HTTPCookieProcessor(CookieJar()))
        if options.https:
            try:
                build_opener(ProxyHandler({}),HTTPSHandler(context=ssl.create_default_context())).open(origin+'/api/health',timeout=3)
            except URLError as exc:check('untrusted_tls_certificate_rejected',isinstance(exc.reason,ssl.SSLCertVerificationError))
            else:check('untrusted_tls_certificate_rejected',False)
        def request(client,path,data=None,csrf=None):
            headers={'Origin':origin,'Content-Type':'application/json'}
            if csrf:headers['X-CSRF-Token']=csrf
            req=Request(origin+path,data=canonical_json(data) if data is not None else None,headers=headers)
            with client.open(req,timeout=4) as response:return json.loads(response.read())
        try:request(first,'/api/incidents')
        except HTTPError as exc:check('unauthenticated_incidents_denied',exc.code==401);exc.close()
        else:check('unauthenticated_incidents_denied',False)
        session=request(first,'/api/login',{'username':'verification-operator','password':password})
        another=request(second,'/api/login',{'username':'verification-operator','password':password})
        check('separate_authenticated_clients',bool(session['csrf_token']) and bool(another['csrf_token']))
        EdgeConfig(origin,'verification-edge',secret,allow_loopback_http=not options.https,ca_file=str(cert) if cert else None).save(work/'edge.json')
        # The existing publisher path is overridden only for isolated test storage;
        # inference, temporal reasoning, transport, auth and store stay actual.
        from unittest.mock import patch
        from sentinal.connected.edge import EdgePublisher
        original=EdgePublisher
        def publisher(config,**kwargs):return original(config,path=work/'outbox/events.sqlite3',**kwargs)
        def observe(packet,current):
            nonlocal preview_seen
            if any(item.category==options.category for item in packet.hazards):hazard_times.add(packet.timestamp)
            if not preview_seen and hazard_times:
                try:
                    with first.open(origin+'/api/cameras/VERIFICATION-CAM/preview.jpg',timeout=2) as response:
                        raw=response.read();stamp=response.headers.get('X-Sentinal-Captured-At')
                    if stamp in hazard_times and raw.startswith(b'\xff\xd8') and raw.endswith(b'\xff\xd9'):preview_seen=True
                except HTTPError as exc:exc.close()
        monitor=monitor_parser().parse_args(['--config',str(work/'edge.json'),'--video',str(video),
            '--camera-id','VERIFICATION-CAM','--name','Authorized public recorded fixture',
            '--detectors',options.detectors,'--display-confidence','.25','--alert-confidence','.35',
            '--persistence','.3','--max-gap','2','--preview','--report',str(work/'monitor.json')])
        with patch('sentinal.connected.monitor.EdgePublisher',publisher):
            execution=run(monitor,on_packet=observe)
        report['monitor']=execution
        check('actual_inference_completed',execution['passed'] and execution['frames_processed']>0)
        check('models_loaded_and_active',any(value.get('status')=='active' for value in execution['model_health'].values()))
        check('genuine_target_observations',bool(hazard_times))
        check('temporal_candidate_precedes_alert',execution['candidate_count']>0 and execution['alert_count']>0)
        items=request(first,'/api/incidents')['items']
        target=next((value for value in items if value['category']==options.category and value['status']=='ALERTED'),None)
        check('signed_event_reaches_real_incident_api',target is not None)
        check('pinned_model_version_and_actual_score',len(target['model_version'])>=7 and 0<=target['confidence']<=1)
        check('annotated_preview_matches_actual_target_frame',preview_seen and execution.get('preview_frames_sent',0)>0)
        ident=target['incident_id']
        check('same_incident_visible_in_second_authenticated_client',any(value['incident_id']==ident for value in request(second,'/api/incidents')['items']))
        acknowledged=request(first,f'/api/incidents/{ident}/review',{'status':'ACKNOWLEDGED','note':'Authorized public test footage reviewed','expected_version':target['version']},session['csrf_token'])
        check('acknowledgment_versioned',acknowledged['status']=='ACKNOWLEDGED' and acknowledged['version']>target['version'])
        synced=request(second,f'/api/incidents/{ident}')
        check('review_synchronizes_between_http_clients',synced['status']=='ACKNOWLEDGED' and synced['version']==acknowledged['version'])
        dismissed=request(second,f'/api/incidents/{ident}/review',{'status':'DISMISSED','note':'Known public demonstration item','expected_version':synced['version']},another['csrf_token'])
        check('second_client_dismissal',dismissed['status']=='DISMISSED')
        audit=request(first,f'/api/incidents/{ident}/audit')['items']
        check('human_review_audit',any(value['action']=='human_review_acknowledged' for value in audit) and any(value['action']=='human_review_dismissed' for value in audit))
        check('all_capture_and_delivery_owners_released',execution['source_released'] and execution['edge_released'] and execution.get('preview_released'))
        report['incident_id']=ident;report['audit_count']=len(audit)
        server.shutdown();server.server_close();thread.join(5);server=None
        store.close();store=Store(work/'backend/server.sqlite3')
        check('dismissal_persists_after_database_reopen',store.incident('default',ident)['status']=='DISMISSED')
        check('no_camera_images_or_evidence_files_saved',not any(path.suffix.lower() in {'.jpg','.jpeg','.png','.mp4','.avi'} for path in work.rglob('*') if path.is_file()))
        report['passed']=all(report['checks'].values())
    except Exception as exc:
        report['failure']=str(exc)
    finally:
        if server is not None:server.shutdown();server.server_close()
        if thread is not None:thread.join(5)
        store.close()
        # Secrets are intentionally not copied to the distributable evidence report.
        report['scope']='Native Python/API integration using two HTTP cookie sessions, not Base44 deployment, browser layout or physical cross-device acceptance.'
        output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({key:value for key,value in report.items() if key!='monitor'},indent=2),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
