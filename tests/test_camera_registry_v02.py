"""Real SQLite/private camera registry and fake-Keychain failure contracts."""
from dataclasses import replace
from pathlib import Path
import stat
import pytest
from sentinal.core.credentials import CredentialStore,CameraCredentials,CredentialError
from sentinal.storage.camera_registry import CameraRegistry

class Keychain:
    def __init__(self):self.data={}
    def put(self,key,payload):self.data[key]=payload
    def get(self,key):return self.data.get(key)
    def delete(self,key):self.data.pop(key,None)

@pytest.fixture
def registry(tmp_path):
    keychain=Keychain();store=CredentialStore(keychain)
    registry=CameraRegistry(tmp_path/'camera-settings/registry.sqlite3',store)
    yield registry,keychain
    registry.close()

def test_session_endpoint_password_and_query_never_reach_sqlite(registry):
    registry,keychain=registry
    record=registry.upsert_network('Entrance','rtsp://viewer:Secret-Test@127.0.0.1:8554/private/token-path?token=TestToken',profile_name='Main')
    selection=registry.resolve(record.camera_id)
    assert selection.password=='Secret-Test' and selection.username=='viewer'
    assert 'TestToken' in selection.spec.value and selection.spec.kind=='stream'
    assert not keychain.data
    registry.connection.commit()
    data=registry.path.read_bytes()
    for secret in [b'Secret-Test',b'TestToken',b'/private',b'token-path',b'viewer']:
        assert secret not in data
        assert secret.decode() not in repr(selection)+repr(record)
    assert stat.S_IMODE(registry.path.stat().st_mode)==0o600
    assert stat.S_IMODE(registry.path.parent.stat().st_mode)==0o700
    registry.credentials.clear_session()
    with pytest.raises(CredentialError,match='session-only'):registry.resolve(record.camera_id)

def test_explicit_keychain_round_trip_and_forget_removes_saved_item(registry):
    registry,keychain=registry
    record=registry.upsert_network('Garage','rtsp://127.0.0.1/secure?token=example','viewer','ExampleSecret',remember=True)
    assert record.camera_id in keychain.data
    registry.credentials.clear_session()
    assert registry.resolve(record.camera_id).password=='ExampleSecret'
    registry.upsert_network('Garage renamed','rtsp://127.0.0.1/new','new-viewer','NewSecret',remember=False,camera_id=record.camera_id)
    assert record.camera_id not in keychain.data
    assert registry.resolve(record.camera_id).password=='NewSecret'
    assert len(registry.list_cameras())==1

def test_persistent_secret_failure_rolls_back_camera_metadata(tmp_path):
    class Refused(Keychain):
        def put(self,*args):raise CredentialError('Keychain unavailable')
    registry=CameraRegistry(tmp_path/'private/registry.sqlite3',CredentialStore(Refused()))
    try:
        with pytest.raises(CredentialError):registry.upsert_network('Entrance','rtsp://127.0.0.1/stream','viewer','Secret',remember=True)
        assert registry.list_cameras()==()
        assert b'Secret' not in registry.path.read_bytes()
    finally:registry.close()

def test_health_is_measured_and_stale_online_state_is_reset_on_reopen(registry):
    registry,keychain=registry
    record=registry.upsert_local('MacBook camera','aabb',0)
    updated=registry.update_health(record.camera_id,connection_health='online',ai_status='active',frame_timestamp='2026-10-30T10:00:00+05:30')
    assert updated.last_frame_utc=='2026-10-30T04:30:00.000+00:00'
    assert updated.connection_health=='online'
    registry.close()
    reopened=CameraRegistry(registry.path,CredentialStore(keychain))
    try:
        restored=reopened.get(record.camera_id)
        assert restored.connection_health=='stopped' and restored.ai_status=='idle'
        assert restored.last_frame_utc==updated.last_frame_utc
    finally:reopened.close()

def test_camera_type_change_and_remove_clear_previous_credentials(registry):
    registry,keychain=registry
    record=registry.upsert_network('Hybrid','rtsp://127.0.0.1/private','user','secret',remember=True)
    registry.upsert_local('Exact local','ccdd',4,camera_id=record.camera_id)
    assert not keychain.data
    assert registry.resolve(record.camera_id).spec.camera_device_id=='ccdd'
    registry.remove(record.camera_id)
    assert registry.get(record.camera_id) is None

@pytest.mark.parametrize('values',[{'name':''},{'name':'Bad\nName'},{'url':'https://example.invalid/'+'x'*9000},{'url':'file:///secret'},{'remember':'false'}])
def test_invalid_settings_do_not_create_camera(registry,values):
    registry,_=registry
    arguments={'name':'Camera','url':'rtsp://127.0.0.1/live'};arguments.update(values)
    with pytest.raises(ValueError):registry.upsert_network(**arguments)
    assert not registry.list_cameras()

def test_invalid_health_or_naive_frame_time_is_rejected(registry):
    registry,_=registry;record=registry.upsert_local('Exact','aabb')
    for options in [{'connection_health':'fake-live'},{'authentication_status':'guessed'},{'ai_status':'pretending'},{'frame_timestamp':'2026-10-30T10:00:00'}]:
        with pytest.raises(ValueError):registry.update_health(record.camera_id,**options)

def test_credential_repr_and_corrupt_keychain_are_safe():
    backend=Keychain();store=CredentialStore(backend)
    credentials=CameraCredentials('rtsp://127.0.0.1/private','name','Secret')
    assert 'Secret' not in repr(credentials)
    backend.data['x']='{"password":"Secret"}'
    with pytest.raises(CredentialError,match='invalid'):store.get('x',remember=True)


def test_refused_forget_preserves_saved_record_and_current_session(tmp_path):
    class RefusedDeletion(Keychain):
        def delete(self,*args):raise CredentialError('Keychain locked')
    backend=RefusedDeletion()
    registry=CameraRegistry(tmp_path/'private/registry.sqlite3',CredentialStore(backend))
    try:
        record=registry.upsert_network('Original','rtsp://127.0.0.1/original','viewer','OriginalSecret',remember=True)
        with pytest.raises(CredentialError):
            registry.upsert_network('Changed','rtsp://127.0.0.1/changed','changed','ChangedSecret',remember=False,camera_id=record.camera_id)
        current=registry.get(record.camera_id)
        assert current.name=='Original' and current.remember
        assert registry.resolve(record.camera_id).password=='OriginalSecret'
        registry.credentials.clear_session()
        assert registry.resolve(record.camera_id).password=='OriginalSecret'
    finally:registry.close()
