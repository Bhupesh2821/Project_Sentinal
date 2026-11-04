"""Connected backend security/persistence tests. Synthetic incidents are labelled fixtures."""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import http.client
import json
import secrets
import threading
import time
from uuid import uuid4

import pytest
from sentinal.connected.protocol import canonical_json, sign_request, validate_event, ProtocolError
from sentinal.connected.server import build_server
from sentinal.connected.store import Store, StoreError

PASSWORD = 'Test-only-passphrase-74622'
SECRET = 'test-only-' + '7' * 40


def now():
    return datetime.now(timezone.utc).isoformat()


def incident_event(device='edge-one', ident='unit-incident'):
    stamp = now()
    return {'schema_version': 1, 'event_id': str(uuid4()), 'kind': 'incident', 'device_id': device, 'occurred_at': stamp,
            'incident': {'incident_id': ident, 'source_id': 'unit-camera', 'session_id': 'unit-session', 'category': 'weapon_knife',
                         'status': 'ALERTED', 'confidence': .85, 'severity': 2, 'model_id': 'unit-test-only-model',
                         'model_version': 'unit-1', 'bbox': [1, 2, 20, 30], 'track_id': 1,
                         'first_seen': stamp, 'last_seen': stamp, 'alerted_at': stamp, 'alert_latency_ms': 0}}


def heartbeat(device='edge-one'):
    return {'schema_version': 1, 'event_id': str(uuid4()), 'kind': 'heartbeat', 'device_id': device, 'occurred_at': now(),
            'health': {'status': 'running', 'processing_fps': 12.5, 'inference_ms': 30.0},
            'cameras': [{'camera_id': 'unit-camera', 'name': 'Unit fixture camera', 'status': 'running', 'last_frame_at': now()}],
            'models': [{'model_id': 'unit-test-only-model', 'version': 'unit-1', 'classes': ['knife'], 'status': 'active', 'device': 'cpu'}]}


class Client:
    def __init__(self, server):
        self.server = server
        self.origin = f'http://127.0.0.1:{server.server_port}'
        self.cookie = ''
        self.csrf = ''

    def request(self, method, path, value=None, headers=None, raw=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        body = canonical_json(value) if value is not None else raw
        options = {'Content-Type': 'application/json'}
        if self.cookie:
            options['Cookie'] = self.cookie
        if method in {'POST', 'PATCH'} and not path.startswith('/api/edge/'):
            options.update(Origin=self.origin, **{'X-CSRF-Token': self.csrf})
        options.update(headers or {})
        connection.request(method, path, body, options)
        result = connection.getresponse()
        data = result.read()
        fields = dict(result.getheaders())
        connection.close()
        if fields.get('Content-Type', '').startswith('application/json'):
            data = json.loads(data)
        return result.status, data, fields

    def login(self, username='owner'):
        status, data, headers = self.request('POST', '/api/login', {'username': username, 'password': PASSWORD})
        assert status == 200, data
        self.cookie = headers['Set-Cookie'].split(';')[0]
        self.csrf = data['csrf_token']
        return data, headers

    def ingest(self, event, **kwargs):
        body = canonical_json(event)
        return self.request('POST', '/api/edge/events', raw=body, headers=sign_request(SECRET, event['device_id'], body, **kwargs))


@pytest.fixture
def service(tmp_path):
    store = Store(tmp_path / 'service/server.sqlite3')
    store.create_user('owner', PASSWORD, 'admin', 'one')
    store.create_user('operator', PASSWORD, 'operator', 'one')
    store.create_user('viewer', PASSWORD, 'viewer', 'one')
    store.create_user('outsider', PASSWORD, 'admin', 'two')
    store.register_device('edge-one', 'Unit edge', SECRET, 'one')
    web = tmp_path / 'web'
    web.mkdir()
    (web / 'index.html').write_text('<!doctype html><title>Public unit fixture</title>')
    (web / 'app.html').write_text('<!doctype html><title>Private data requires API login</title>')
    server = build_server(store, port=0, web_root=web, allow_local_preview=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    yield store, server, Client(server)
    server.shutdown()
    server.server_close()
    thread.join(3)
    store.close()


def test_end_to_end_signed_event_private_review_persists(service):
    store, server, client = service
    assert client.request('GET', '/api/incidents')[0] == 401
    event = incident_event()
    status, result, _ = client.ingest(event)
    assert status == 201 and result['event_id'] == event['event_id']
    assert client.ingest(event)[0:2] == (200, {'ok': True, 'event_id': event['event_id'], 'duplicate': True})
    user, headers = client.login()
    assert 'HttpOnly' in headers['Set-Cookie'] and 'SameSite=Strict' in headers['Set-Cookie']
    status, body, _ = client.request('GET', '/api/incidents')
    assert status == 200 and len(body['items']) == 1
    row = body['items'][0]
    status, reviewed, _ = client.request('POST', '/api/incidents/unit-incident/review', {'status': 'ACKNOWLEDGED', 'note': 'Known unit fixture', 'expected_version': row['version']})
    assert status == 200 and reviewed['status'] == 'ACKNOWLEDGED' and reviewed['version'] == 2
    status, _, _ = client.request('POST', '/api/incidents/unit-incident/review', {'status': 'DISMISSED', 'note': 'Stale version', 'expected_version': 1})
    assert status == 409
    status, reviewed, _ = client.request('POST', '/api/incidents/unit-incident/review', {'status': 'DISMISSED', 'note': 'Known fixture', 'expected_version': 2})
    assert status == 200 and reviewed['status'] == 'DISMISSED'
    assert store.incident('one', 'unit-incident')['reviewed_by'] == user['user']['id']
    assert len(client.request('GET', '/api/incidents/unit-incident/audit')[1]['items']) == 3
    assert client.request('POST', '/api/logout', {})[0] == 200
    assert client.request('GET', '/api/incidents')[0] == 401


def test_modified_body_bad_secret_expired_and_replay_are_rejected(service):
    _, _, client = service
    event = incident_event()
    body = canonical_json(event)
    headers = sign_request(SECRET, 'edge-one', body)
    altered = dict(event)
    altered['occurred_at'] = now()
    assert client.request('POST', '/api/edge/events', raw=canonical_json(altered), headers=headers)[0] == 401
    assert client.request('POST', '/api/edge/events', raw=body, headers=headers)[0] == 201
    assert client.request('POST', '/api/edge/events', raw=body, headers=headers)[0] == 409
    assert client.ingest(incident_event(), timestamp=str(int(time.time()) - 1000))[0] == 401
    wrong = sign_request('bad-secret-' * 5, 'edge-one', body)
    assert client.request('POST', '/api/edge/events', raw=body, headers=wrong)[0] == 401


def test_event_identity_conflict_and_device_body_mismatch(service):
    store, _, client = service
    event = incident_event()
    assert client.ingest(event)[0] == 201
    event['incident']['confidence'] = .7
    assert client.ingest(event)[0] == 409
    body = canonical_json(incident_event(device='other'))
    assert client.request('POST', '/api/edge/events', raw=body, headers=sign_request(SECRET, 'edge-one', body))[0] == 401
    assert len(store.incidents('one')) == 1


def test_roles_and_organizations_cannot_leak_or_review(service):
    _, server, client = service
    assert client.ingest(incident_event())[0] == 201
    outsider = Client(server)
    outsider.login('outsider')
    assert outsider.request('GET', '/api/incidents')[1]['items'] == []
    assert outsider.request('GET', '/api/incidents/unit-incident')[0] == 404
    assert outsider.request('GET', '/api/incidents/unit-incident/audit')[0] == 404
    assert outsider.request('POST', '/api/incidents/unit-incident/review', {'status': 'ACKNOWLEDGED', 'note': '', 'expected_version': 1})[0] == 404
    viewer = Client(server)
    viewer.login('viewer')
    assert len(viewer.request('GET', '/api/incidents')[1]['items']) == 1
    assert viewer.request('POST', '/api/incidents/unit-incident/review', {'status': 'ACKNOWLEDGED', 'note': '', 'expected_version': 1})[0] == 403
    for path in ('/api/users', '/api/audit', '/api/settings'):
        assert viewer.request('GET', path)[0] == 403


def test_csrf_origin_host_and_security_headers(service):
    _, _, client = service
    client.ingest(incident_event())
    client.login()
    action = {'status': 'ACKNOWLEDGED', 'note': '', 'expected_version': 1}
    assert client.request('POST', '/api/incidents/unit-incident/review', action, headers={'X-CSRF-Token': ''})[0] == 403
    assert client.request('POST', '/api/incidents/unit-incident/review', action, headers={'Origin': 'https://evil.example'})[0] == 403
    assert client.request('GET', '/api/incidents', headers={'Host': 'evil.example'})[0] == 421
    status, _, headers = client.request('GET', '/')
    assert status == 200 and headers['X-Content-Type-Options'] == 'nosniff'
    assert "script-src 'self'" in headers['Content-Security-Policy'] and 'unsafe-inline' not in headers['Content-Security-Policy']
    assert headers['Cache-Control'] == 'no-store' and 'Access-Control-Allow-Origin' not in headers
    assert client.request('GET', '/config/settings.json')[0] == 404
    assert client.request('GET', '/%2e%2e/recordings/connected/server.sqlite3')[0] == 404
    assert client.request('POST', '/api/login', {'username': 'owner', 'password': PASSWORD}, headers={'Origin': 'https://evil.example'})[0] == 403


def test_edge_cannot_forge_human_review_or_unknown_fields(service):
    _, _, client = service
    event = incident_event()
    event['incident']['status'] = 'VERIFIED'
    assert client.ingest(event)[0] == 400
    event = incident_event()
    event['organization'] = 'two'
    assert client.ingest(event)[0] == 400
    event = heartbeat()
    event['cameras'][0]['rtsp_url'] = 'rtsp://private'
    assert client.ingest(event)[0] == 400
    assert client.request('GET', '/api/health')[1]['status'] == 'ok'


def test_heartbeat_actual_metrics_models_and_staleness(service):
    store, _, client = service
    assert client.ingest(heartbeat())[0] == 201
    client.login()
    devices = client.request('GET', '/api/devices')[1]['items']
    assert devices[0]['health']['processing_fps'] == 12.5 and devices[0]['status'] == 'running'
    assert client.request('GET', '/api/cameras')[1]['items'][0]['name'] == 'Unit fixture camera'
    assert client.request('GET', '/api/models')[1]['items'][0]['classes'] == ['knife']
    with store.transaction():
        store.db.execute('UPDATE devices SET received_at=?', (time.time() - 46,))
    assert client.request('GET', '/api/devices')[1]['items'][0]['status'] == 'offline'
    assert client.request('GET', '/api/cameras')[1]['items'][0]['status'] == 'offline'
    assert client.request('GET', '/api/models')[1]['items'][0]['status'] == 'unavailable'


def test_received_edge_update_does_not_overwrite_human_review(service):
    store, _, client = service
    event = incident_event()
    client.ingest(event)
    client.login('operator')
    assert client.request('POST', '/api/incidents/unit-incident/review', {'status': 'ACKNOWLEDGED', 'note': 'Unit review', 'expected_version': 1})[0] == 200
    event['event_id'] = str(uuid4())
    event['incident']['last_seen'] = now()
    assert client.ingest(event)[0] == 201
    assert store.incident('one', 'unit-incident')['status'] == 'ACKNOWLEDGED'
    assert store.incident('one', 'unit-incident')['version'] == 2


def test_local_preview_auth_scope_expiry_and_no_persistence(service):
    store, server, client = service
    assert client.ingest(heartbeat())[0] == 201
    # Minimal JPEG markers are intentionally not an image/vision acceptance test.
    jpeg = b'\xff\xd8unit-transport-fixture\xff\xd9'
    payload = {'device_id': 'edge-one', 'camera_id': 'unit-camera', 'captured_at': now(), 'jpeg_base64': base64.b64encode(jpeg).decode()}
    body = canonical_json(payload)
    status, _, _ = client.request('POST', '/api/edge/preview', raw=body, headers=sign_request(SECRET, 'edge-one', body, path='/api/edge/preview'))
    assert status == 200
    assert client.request('GET', '/api/cameras/unit-camera/preview.jpg')[0] == 401
    client.login()
    assert client.request('GET', '/api/cameras')[1]['items'][0]['preview_available']
    status, data, headers = client.request('GET', '/api/cameras/unit-camera/preview.jpg')
    assert status == 200 and data == jpeg and headers['Cache-Control'] == 'no-store'
    outsider = Client(server)
    outsider.login('outsider')
    assert outsider.request('GET', '/api/cameras/unit-camera/preview.jpg')[0] == 404
    with server.preview_lock:
        server.previews[('one', 'unit-camera')]['received'] -= 4
    assert client.request('GET', '/api/cameras/unit-camera/preview.jpg')[0] == 404
    assert not any(p.suffix in {'.jpg', '.jpeg'} for p in store.path.parent.rglob('*'))
    server.allow_local_preview = False
    assert client.request('POST', '/api/edge/preview', raw=body, headers=sign_request(SECRET, 'edge-one', body, path='/api/edge/preview'))[0] == 409


def test_external_http_and_preview_exposure_fail_closed(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    try:
        with pytest.raises(ValueError, match='TLS'):
            build_server(store, host='0.0.0.0')
        with pytest.raises(ValueError, match='loopback'):
            build_server(store, host='127.0.0.1', public_origin='https://sentinal.example', allow_local_preview=True)
        with pytest.raises(ValueError, match='HTTPS'):
            build_server(store, public_origin='http://sentinal.example')
    finally:
        store.close()


def test_store_persists_reviews_and_keeps_only_password_and_session_hashes(tmp_path):
    path = tmp_path / 'persistent/server.sqlite3'
    store = Store(path)
    user = store.create_user('owner', PASSWORD)
    store.register_device('edge-one', 'Unit edge', SECRET)
    event = incident_event()
    store.ingest(event, hashlib.sha256(canonical_json(event)).hexdigest(), store.device('edge-one'))
    token, _ = store.login('owner', PASSWORD, 'unit')
    store.review(user, 'unit-incident', 'ACKNOWLEDGED', 'Persist this unit review', 1)
    raw = b''.join(p.read_bytes() for p in path.parent.iterdir() if p.is_file())
    assert PASSWORD.encode() not in raw and token.encode() not in raw and SECRET.encode() not in raw
    store.close()
    reopened = Store(path)
    try:
        assert reopened.incident('default', 'unit-incident')['status'] == 'ACKNOWLEDGED'
        assert reopened.session(token)['id'] == user['id']
        assert path.stat().st_mode & 0o077 == 0
    finally:
        reopened.close()


def test_admin_creates_role_and_updates_retention(service):
    _, server, client = service
    client.login()
    result = client.request('POST', '/api/users', {'username': 'new-viewer', 'password': PASSWORD, 'role': 'viewer'})
    assert result[0] == 201 and result[1]['role'] == 'viewer'
    assert len(client.request('GET', '/api/users')[1]['items']) == 4
    assert client.request('PATCH', '/api/settings', {'retention_days': 3})[1]['retention_days'] == 3
    assert client.request('PATCH', '/api/settings', {'retention_days': 0})[0] == 400
    assert any(row['action'] == 'retention_updated' for row in client.request('GET', '/api/audit')[1]['items'])


def test_login_rate_limit_and_request_validation(service):
    _, _, client = service
    for _ in range(8):
        assert client.request('POST', '/api/login', {'username': 'missing', 'password': 'wrong-long-password'})[0] == 401
    status, _, headers = client.request('POST', '/api/login', {'username': 'missing', 'password': 'wrong-long-password'})
    assert status == 429 and 'Retry-After' in headers
    assert client.request('POST', '/api/edge/events', raw=b'{}', headers={'Content-Type': 'text/plain'})[0] == 415
    assert client.request('POST', '/api/edge/events', raw=b'{}')[0] == 401


def test_invalid_numeric_and_duplicate_json_are_rejected(service):
    _, _, client = service
    event = incident_event()
    event['incident']['confidence'] = float('nan')
    with pytest.raises(ValueError):
        canonical_json(event)
    raw = b'{"schema_version":1,"schema_version":2}'
    assert client.request('POST', '/api/edge/events', raw=raw, headers=sign_request(SECRET, 'edge-one', raw))[0] == 400
    client.login()
    assert client.request('GET', '/api/incidents?limit=nan')[0] == 400
    assert client.request('GET', '/api/incidents?limit=1&limit=2')[0] == 400


def test_delayed_heartbeat_does_not_resurrect_stale_health(service):
    store, _, client = service
    fresh = heartbeat()
    assert client.ingest(fresh)[0] == 201
    delayed = heartbeat()
    delayed['occurred_at'] = datetime.fromtimestamp(time.time() - 3600, timezone.utc).isoformat()
    delayed['health']['status'] = 'error'
    assert client.ingest(delayed)[0] == 201
    assert store.devices('one')[0]['status'] == 'running'
    # A device's only queued old heartbeat also remains explicitly historical.
    store.register_device('stale-edge', 'Delayed fixture', SECRET, 'one')
    delayed['device_id'] = 'stale-edge';delayed['event_id'] = str(uuid4());delayed['cameras'] = []
    assert client.ingest(delayed)[0] == 201
    stale = next(device for device in store.devices('one') if device['device_id'] == 'stale-edge')
    assert stale['status'] == 'offline' and stale['measurement_status'] == 'historical'


def test_administrator_can_revoke_device_and_reject_future_deliveries(service):
    _, server, client = service
    client.login()
    assert client.ingest(heartbeat())[0] == 201
    outsider = Client(server);outsider.login('outsider')
    assert outsider.request('POST', '/api/devices/edge-one/disable', {})[0] == 404
    assert client.request('POST', '/api/devices/edge-one/disable', {})[0] == 200
    assert client.ingest(incident_event())[0] == 401
    device = client.request('GET', '/api/devices')[1]['items'][0]
    assert not device['enabled'] and device['status'] == 'offline'


def test_concurrent_review_has_one_winner_and_durable_version(service):
    store, _, client = service
    client.ingest(incident_event())
    user = store.session(store.login('operator', PASSWORD, 'unit-concurrent')[0])
    results = []
    barrier = threading.Barrier(2)
    def review(status):
        barrier.wait()
        try:
            results.append(store.review(user, 'unit-incident', status, 'Concurrent unit review', 1)['status'])
        except StoreError as exc:
            results.append(exc.status)
    first = threading.Thread(target=review, args=('ACKNOWLEDGED',));second = threading.Thread(target=review, args=('DISMISSED',))
    first.start();second.start();first.join(3);second.join(3)
    assert results.count(409) == 1 and len(results) == 2
    assert store.incident('one', 'unit-incident')['version'] == 2
    assert len(store.audit('one', 'unit-incident')) == 2


def test_nonce_replay_protection_survives_server_store_restart(tmp_path):
    path = tmp_path / 'nonce/server.sqlite3'
    first = Store(path)
    first.register_device('edge-one', 'Unit edge', SECRET)
    nonce = secrets.token_hex(16)
    first.accept_nonce('edge-one', nonce)
    first.close()
    second = Store(path)
    try:
        with pytest.raises(StoreError) as failure:
            second.accept_nonce('edge-one', nonce)
        assert failure.value.status == 409
    finally:
        second.close()


def test_actual_tls_login_sets_secure_cookie(tmp_path):
    import shutil
    import ssl
    import subprocess
    openssl = shutil.which('openssl')
    if openssl is None:
        pytest.skip('OpenSSL certificate tool unavailable; TLS test is not claimed')
    directory = tmp_path / 'tls'
    directory.mkdir()
    config = directory / 'certificate.conf'
    config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n')
    cert, key = directory / 'cert.pem', directory / 'key.pem'
    subprocess.run([openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-keyout', str(key), '-out', str(cert), '-config', str(config)], check=True, capture_output=True)
    store = Store(directory / 'server.sqlite3')
    store.create_user('owner', PASSWORD)
    server = build_server(store, port=0, web_root=directory, tls_cert=cert, tls_key=key)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        context = ssl.create_default_context(cafile=cert)
        connection = http.client.HTTPSConnection('127.0.0.1', server.server_port, context=context, timeout=5)
        connection.request('POST', '/api/login', canonical_json({'username': 'owner', 'password': PASSWORD}), {'Content-Type': 'application/json', 'Origin': f'https://127.0.0.1:{server.server_port}'})
        response = connection.getresponse()
        headers = dict(response.getheaders())
        assert response.status == 200 and json.loads(response.read())['user']['username'] == 'owner'
        assert '; Secure' in headers['Set-Cookie'] and headers['Strict-Transport-Security'] == 'max-age=31536000'
        assert connection.sock.version() in {'TLSv1.2', 'TLSv1.3'}
        connection.close()
    finally:
        server.shutdown();server.server_close();thread.join(3);store.close()


def test_two_independent_browser_sessions_share_authoritative_review(service):
    _, server, first = service
    first.login()
    second = Client(server);second.login()
    assert first.cookie != second.cookie
    first.ingest(incident_event())
    second_row = second.request('GET', '/api/incidents')[1]['items'][0]
    assert second.request('POST', '/api/incidents/unit-incident/review', {'status': 'ACKNOWLEDGED', 'note': 'Review from another session', 'expected_version': second_row['version']})[0] == 200
    assert first.request('GET', '/api/incidents')[1]['items'][0]['status'] == 'ACKNOWLEDGED'
    first.request('POST', '/api/logout', {})
    assert first.request('GET', '/api/session')[0] == 401
    assert second.request('GET', '/api/session')[0] == 200


def test_retention_deletes_expired_incidents_and_receipts_prevent_resurrection(service):
    store, _, client = service
    event = incident_event()
    client.ingest(event)
    with store.transaction():
        store.db.execute('UPDATE incidents SET received_at=?', (datetime.fromtimestamp(time.time() - 8 * 86400, timezone.utc).isoformat(),))
    client.login()
    assert client.request('PATCH', '/api/settings', {'retention_days': 3})[0] == 200
    assert client.request('GET', '/api/incidents')[1]['items'] == []
    assert client.ingest(event)[1]['duplicate']
    assert client.request('GET', '/api/incidents')[1]['items'] == []


def test_camera_owner_cannot_be_forged_by_other_device_in_same_organization(service):
    store, _, client = service
    client.ingest(heartbeat())
    store.register_device('another-edge', 'Another unit device', SECRET, 'one')
    assert client.ingest(incident_event(device='another-edge'))[0] == 403
    assert store.incidents('one') == []


def test_revocation_is_rechecked_inside_ingestion_transaction(service):
    store, _, client = service
    device = store.device('edge-one')
    token, user = store.login('owner', PASSWORD, 'unit-race')
    store.disable_device(user, 'edge-one')
    event = incident_event()
    with pytest.raises(StoreError) as failure:
        store.ingest(event, hashlib.sha256(canonical_json(event)).hexdigest(), device)
    assert failure.value.status == 401 and store.incidents('one') == []
