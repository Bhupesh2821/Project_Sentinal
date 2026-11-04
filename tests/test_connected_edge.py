"""Outbound integration with actual local HTTP/SQLite and identified synthetic metadata.

These tests do not establish AI accuracy; the separate real-inference verifier
uses genuine model outputs before submitting them through these implementations.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from dataclasses import replace
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from uuid import uuid4
import pytest

from sentinal.connected.edge import (EdgeConfig, EdgePublisher, HTTPTransport,
    DeliveryResult, incident_event, heartbeat_event, _retry_after)
from sentinal.connected.outbox import Outbox, PendingEvent
from sentinal.connected.protocol import canonical_json, sign_request

SECRET='synthetic-unit-secret-'+'1'*32
DEVICE='unit-edge'


def incident(status='ALERTED'):
    stamp=datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    return {'incident_id':str(uuid4()),'source_id':'unit-camera','session_id':str(uuid4()),
        'category':'fire','status':status,'confidence':.82,'severity':3,
        'model_id':'synthetic-unit-model','model_version':'unit-1','bbox':(1,2,30,40),
        'track_id':1,'first_seen':stamp,'last_seen':stamp,
        'alerted_at':stamp if status=='ALERTED' else None,'alert_latency_ms':500 if status=='ALERTED' else None}


def config(url='http://127.0.0.1:12345',**kwargs):
    return EdgeConfig(url,DEVICE,SECRET,allow_loopback_http=True,**kwargs)


def wait(predicate,seconds=5):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.005)
    raise AssertionError('Outbound test condition was not reached')


@contextmanager
def server(response=None):
    observed=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=self.rfile.read(int(self.headers['Content-Length']))
            record={'path':self.path,'body':body,'headers':dict(self.headers)};observed.append(record)
            if response:
                code,headers,raw=response(record,len(observed))
            else:
                expected=sign_request(SECRET,DEVICE,body,timestamp=self.headers.get('X-Sentinal-Timestamp'),nonce=self.headers.get('X-Sentinal-Nonce'))
                assert hmac.compare_digest(expected['X-Sentinal-Signature'],self.headers['X-Sentinal-Signature'])
                value=json.loads(body)
                code,headers,raw=201,{'Content-Type':'application/json'},canonical_json({'ok':True,'event_id':value['event_id']})
            self.send_response(code)
            for name,value in headers.items():self.send_header(name,value)
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    owner=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=owner.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{owner.server_address[1]}',observed
    finally:owner.shutdown();owner.server_close();thread.join(2)


@pytest.mark.parametrize('url',['http://192.168.1.10','http://localhost:8080','https://u:p@example.test','https://example.test/api','https://example.test/?token=secret','file:///tmp/data','https://example.test:0'])
def test_connection_rejects_unsecured_remote_endpoints_and_embedded_secrets(url):
    with pytest.raises(ValueError):config(url)


def test_http_requires_runtime_explicit_loopback_opt_in():
    with pytest.raises(ValueError):EdgeConfig('http://127.0.0.1:8000',DEVICE,SECRET)
    assert EdgeConfig('https://backend.example.test',DEVICE,SECRET).endpoint.endswith('/api/edge/events')


def test_credentials_owner_only_storage_does_not_enable_or_create_outbox(tmp_path):
    path=tmp_path/'credentials/device.json';cfg=config();cfg.save(path)
    assert path.stat().st_mode&0o077==0
    assert EdgeConfig.load(path)==cfg
    assert SECRET not in repr(cfg) and 'enabled' not in path.read_text()
    pub=EdgePublisher(cfg,tmp_path/'not-created/outbox.sqlite3')
    assert not pub.path.exists() and pub.status()['state']=='disabled'
    assert not pub.submit_incident(incident()) and pub.close()
    path.chmod(0o644)
    with pytest.raises(ValueError,match='only'):EdgeConfig.load(path)


def test_incident_projection_strips_reviews_evidence_and_has_stable_id():
    row=incident();row.update(evidence_path='/private/frame.jpg',review_note='private human note',stream_url='rtsp://secret:password@camera')
    event=incident_event(row,DEVICE)
    assert event['event_id']==incident_event(row,DEVICE)['event_id']
    body=canonical_json(event)
    assert b'private' not in body and b'rtsp' not in body and b'review_note' not in body
    assert event['incident']['confidence']==row['confidence']
    assert incident_event(incident('CANDIDATE'),DEVICE) is None
    assert incident_event(incident('ACKNOWLEDGED'),DEVICE) is None
    row['source_id']='rtsp://user:pass@camera'
    with pytest.raises(ValueError):incident_event(row,DEVICE)


def test_heartbeat_allowlist_rejects_stream_credentials_and_omits_unavailable_metrics():
    value=heartbeat_event(DEVICE,{'status':'running','processing_fps':12.3,'memory_rss_mb':None},
        [{'camera_id':'CAM-1','name':'Door','status':'running'}],
        [{'model_id':'model','version':'1','classes':['fire'],'status':'active','device':'cpu'}])
    assert value['health']=={'status':'running','processing_fps':12.3}
    with pytest.raises(ValueError):heartbeat_event(DEVICE,{'status':'running','stream_url':'rtsp://camera'})
    with pytest.raises(ValueError):heartbeat_event(DEVICE,{'status':'error','message':'Failed at rtsp://user:pass@camera'})
    with pytest.raises(ValueError):heartbeat_event(DEVICE,{'status':'idle'},[{'camera_id':'x','name':'Door','status':'idle','password':'secret'}])


def test_outbox_persists_exact_bytes_idempotency_capacity_and_retention(tmp_path):
    path=tmp_path/'spool/events.sqlite3';first=incident_event(incident(),DEVICE)
    owner=Outbox(path,max_events=1,max_age_s=60)
    try:
        assert owner.enqueue(first,now=100)
        assert not owner.enqueue(first,now=101)
        changed=json.loads(canonical_json(first));changed['incident']['confidence']=.83
        with pytest.raises(ValueError,match='changed'):owner.enqueue(changed,now=101)
        with pytest.raises(OverflowError):owner.enqueue(incident_event(incident(),DEVICE),now=101)
        expected=owner.ready(101);assert expected.payload==canonical_json(first)
        owner.retry(first['event_id'],10,'bounded diagnostic',now=101)
        assert owner.ready(105) is None and owner.ready(111).attempts==1
    finally:owner.close()
    owner=Outbox(path,max_events=1,max_age_s=60)
    try:
        assert owner.ready(111).payload==canonical_json(first)
        owner.failed(first['event_id']);assert owner.counts()=={'queued':0,'failed':1}
        assert owner.expire(now=161)==1 and owner.counts()=={'queued':0,'failed':0}
    finally:owner.close()
    assert path.stat().st_mode&0o077==0


def test_outbox_rejects_extra_unapproved_frame_field(tmp_path):
    value=incident_event(incident(),DEVICE);value['frame']='base64-private-video'
    owner=Outbox(tmp_path/'spool.sqlite3')
    try:
        with pytest.raises(ValueError):owner.enqueue(value)
        assert owner.counts()=={'queued':0,'failed':0}
    finally:owner.close()


def test_real_signed_http_delivery_acknowledges_and_releases_spool(tmp_path):
    with server() as (url,observed):
        pub=EdgePublisher(config(url),tmp_path/'spool/events.sqlite3');pub.start()
        try:
            assert pub.submit_incident(incident())
            wait(lambda:pub.status()['delivered']==1 and pub.status()['queued']==0)
            assert len(observed)==1 and observed[0]['path']=='/api/edge/events'
            assert pub.status()['state']=='connected' and pub.status()['last_delivery_at']
        finally:assert pub.close()
    owner=Outbox(tmp_path/'spool/events.sqlite3')
    try:assert owner.counts()=={'queued':0,'failed':0}
    finally:owner.close()


def test_retry_uses_identical_event_body_but_fresh_signature_nonce(tmp_path):
    def first_busy(record,index):
        if index==1:return 503,{'Retry-After':'0'},b'private upstream detail'
        value=json.loads(record['body']);return 200,{'Content-Type':'application/json'},canonical_json({'ok':True,'event_id':value['event_id'],'duplicate':True})
    with server(first_busy) as (url,observed):
        pub=EdgePublisher(config(url),tmp_path/'spool.sqlite3');pub.start()
        try:
            pub.submit_incident(incident());wait(lambda:pub.status()['delivered']==1)
            assert len(observed)==2 and observed[0]['body']==observed[1]['body']
            assert observed[0]['headers']['X-Sentinal-Nonce']!=observed[1]['headers']['X-Sentinal-Nonce']
            assert 'private upstream' not in str(pub.status())
        finally:assert pub.close()


def test_authentication_failure_is_not_retried_forever(tmp_path):
    with server(lambda *_:(401,{'Content-Type':'application/json'},b'{"token":"do not retain"}')) as (url,observed):
        pub=EdgePublisher(config(url),tmp_path/'spool.sqlite3');pub.start()
        try:
            pub.submit_incident(incident());wait(lambda:pub.status()['failed']==1)
            time.sleep(.3)
            assert len(observed)==1 and pub.status()['delivered']==0
            assert 'do not retain' not in str(pub.status())
        finally:assert pub.close()


def test_redirect_does_not_forward_device_headers(tmp_path):
    with server() as (destination,leaked):
        with server(lambda *_:(302,{'Location':destination+'/leak'},b'')) as (url,observed):
            event=incident_event(incident(),DEVICE)
            result=HTTPTransport(config(url)).send(PendingEvent(event['event_id'],canonical_json(event),0,time.time()))
            assert not result.accepted and not result.retryable and not leaked and len(observed)==1


def test_wrong_or_malformed_ack_does_not_drop_unsent_incident(tmp_path):
    with server(lambda *_:(200,{'Content-Type':'application/json'},b'{"ok":true,"event_id":"wrong"}')) as (url,_):
        pub=EdgePublisher(config(url,max_attempts=1),tmp_path/'spool.sqlite3');pub.start()
        try:
            pub.submit_incident(incident());wait(lambda:pub.status()['failed']==1)
            assert pub.status()['delivered']==0 and 'match' in pub.status()['last_error']
        finally:assert pub.close()


def test_queue_is_bounded_and_submit_does_not_wait_for_network(tmp_path):
    entered=threading.Event();release=threading.Event()
    class BlockedTransport:
        def send(self,pending):entered.set();release.wait(2);return DeliveryResult(True)
    pub=EdgePublisher(config(),tmp_path/'spool.sqlite3',queue_size=2,transport=BlockedTransport());pub.start()
    try:
        assert pub.submit_incident(incident());assert entered.wait(2)
        start=time.monotonic()
        assert pub.submit_incident(incident()) and pub.submit_incident(incident())
        assert not pub.submit_incident(incident())
        assert time.monotonic()-start<.2 and pub.status()['dropped']==1
        pub.request_stop();release.set();assert pub.close()
    finally:release.set();pub.close()
    owner=Outbox(tmp_path/'spool.sqlite3')
    try:assert owner.counts()['queued']==2
    finally:owner.close()


@pytest.mark.parametrize('value,expected',[('0',0),('120',120),('999999',3600),('nan',None),('junk',None)])
def test_retry_after_is_bounded(value,expected):
    assert _retry_after(value)==expected


def test_qt_bridge_default_off_and_real_service_signal_only_sends_after_enable(tmp_path):
    from PySide6.QtWidgets import QApplication
    from sentinal.connected.integration import DesktopEdgeBridge
    from sentinal.core.incident_worker import IncidentWorker
    app=QApplication.instance() or QApplication([])
    bridge=DesktopEdgeBridge(path=tmp_path/'connected/outbox.sqlite3')
    service=IncidentWorker(path=tmp_path/'not-created/incidents.sqlite3')
    bridge.attach(service);bridge.attach(service)
    service.incident_changed.emit(incident())
    assert not bridge.is_running and not service.path.exists() and not (tmp_path/'connected').exists()
    def spin(predicate):
        end=time.monotonic()+5
        while time.monotonic()<end:
            app.processEvents()
            if predicate():return
            time.sleep(.005)
        raise AssertionError('Qt edge bridge did not complete expected transition')
    with server() as (url,observed):
        bridge.set_health_provider(lambda:{'health':{'status':'running','processing_fps':7.5},'cameras':[{'camera_id':'CAM1','name':'Unit fixture','status':'running'}]})
        try:
            bridge.start(config(url));spin(lambda:bridge.status()['delivered']>=1)
            row=incident();service.incident_changed.emit(row)
            spin(lambda:bridge.status()['delivered']>=2)
            kinds=[json.loads(value['body'])['kind'] for value in observed]
            assert kinds.count('incident')==1 and kinds.count('heartbeat')==1
            bridge.stop();assert not bridge.is_enabled
            service.incident_changed.emit(incident())
            assert bridge.close()
            assert len(observed)==2 and not service.path.exists()
        finally:bridge.close()


def test_malformed_health_provider_is_reported_without_upload(tmp_path):
    from PySide6.QtWidgets import QApplication
    from sentinal.connected.integration import DesktopEdgeBridge
    app=QApplication.instance() or QApplication([])
    bridge=DesktopEdgeBridge(path=tmp_path/'connected/outbox.sqlite3');errors=[]
    bridge.error.connect(errors.append)
    with server() as (url,observed):
        bridge.set_health_provider(lambda:{'health':{'status':'running'},'frame':'private pixels'})
        try:
            bridge.start(config(url));app.processEvents()
            assert errors and not observed
        finally:assert bridge.close()


def test_connection_changes_never_forward_another_destinations_pending_events(tmp_path):
    path=tmp_path/'outbox.sqlite3';original=config()
    box=Outbox(path,destination=original.destination_key)
    try:box.enqueue(incident_event(incident(),DEVICE))
    finally:box.close()
    sent=[]
    class Transport:
        def send(self,pending):sent.append(pending);return DeliveryResult(True)
    other=replace(original,device_id='another-device')
    publisher=EdgePublisher(other,path=path,transport=Transport());publisher.start();publisher.join(2)
    assert not publisher.is_alive() and not sent
    assert 'another device connection' in publisher.status()['last_error']
    box=Outbox(path,destination=original.destination_key)
    try:assert box.counts()['queued']==1
    finally:box.close()
    # Automatic stores are distinct when any destination authority changes.
    assert EdgePublisher(original).path!=EdgePublisher(other).path
    assert EdgePublisher(original).path!=EdgePublisher(replace(original,server_url='http://127.0.0.1:22222')).path
    assert EdgePublisher(original).path!=EdgePublisher(replace(original,secret='rotated-'+'x'*48)).path


def test_unbound_legacy_queue_cannot_be_silently_assigned_to_a_new_connection(tmp_path):
    from sentinal.connected.outbox import OutboxDestinationError
    path=tmp_path/'outbox.sqlite3';box=Outbox(path)
    try:box.enqueue(incident_event(incident(),DEVICE))
    finally:box.close()
    with pytest.raises(OutboxDestinationError,match='explicit migration'):Outbox(path,destination=config().destination_key)
    box=Outbox(path)
    try:assert box.counts()['queued']==1
    finally:box.close()


def test_cloud_gateway_path_allowlist_preserves_logical_signature_and_old_config(tmp_path):
    base=EdgeConfig('https://app.example.test',DEVICE,SECRET)
    cloud=replace(base,ingest_path='/functions/ingest')
    assert cloud.endpoint=='https://app.example.test/functions/ingest'
    assert base.destination_key!=cloud.destination_key
    value=incident_event(incident(),DEVICE)
    # HTTP path changes only transport; the reviewed gateway verifies the stable
    # logical protocol action /api/edge/events, samebody/signer as local API.
    signed=sign_request(cloud.secret,cloud.device_id,canonical_json(value),timestamp='100',nonce='a'*32)
    assert signed==sign_request(base.secret,base.device_id,canonical_json(value),timestamp='100',nonce='a'*32)
    path=tmp_path/'credentials/cloud.json';cloud.save(path)
    assert EdgeConfig.load(path).ingest_path=='/functions/ingest'
    raw=json.loads(path.read_text());raw.pop('ingest_path');path.write_text(json.dumps(raw));path.chmod(0o600)
    assert EdgeConfig.load(path).ingest_path=='/api/edge/events'
    with pytest.raises(ValueError,match='Unsupported'):replace(base,ingest_path='/unreviewed/path')


@pytest.mark.parametrize('changes',[{'server_url':42},{'server_url':float('nan')},
    {'ingest_path':[]},{'ingest_path':{}},{'ca_file':42},{'ca_file':{}}])
def test_corrupted_credentials_types_report_value_error_without_traceback(changes):
    with pytest.raises(ValueError):replace(config(),**changes)
