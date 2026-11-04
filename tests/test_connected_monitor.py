"""Headless-source/preview contracts, distinct from real model verification."""
import numpy as np
import pytest
from sentinal.connected.monitor import parser,source_spec,model_metadata
from sentinal.connected.edge import EdgeConfig
from sentinal.connected.preview import PreviewPublisher,annotated_jpeg


def test_monitor_requires_explicit_source_and_preview_starts_off(tmp_path):
    with pytest.raises(SystemExit):parser().parse_args([])
    path=tmp_path/'input.mp4';path.write_bytes(b'Synthetic source metadata test')
    args=parser().parse_args(['--video',str(path)])
    assert not args.preview and not args.loop and not args.unpaced
    assert source_spec(args).kind=='file'


def test_explicit_camera_identity_and_no_index_fallback():
    args=parser().parse_args(['--camera-device-id','616263'])
    spec=source_spec(args)
    assert spec.kind=='camera' and spec.camera_device_id=='616263'
    args.camera_device_id=''
    with pytest.raises(ValueError,match='exact'):source_spec(args)


def test_stream_credential_file_owner_only_and_never_in_repr(tmp_path):
    path=tmp_path/'stream.txt';path.write_text('rtsp://authorized:secret-password@127.0.0.1:18554/live')
    args=parser().parse_args(['--stream-url-file',str(path)])
    path.chmod(0o644)
    with pytest.raises(ValueError,match='owner-only'):source_spec(args)
    path.chmod(0o600);spec=source_spec(args)
    assert spec.kind=='stream' and 'secret-password' not in repr(spec)


def test_preview_cannot_target_public_or_lan_backend():
    cfg=EdgeConfig('https://example.test','unit','s'*48)
    with pytest.raises(ValueError,match='loopback'):PreviewPublisher(cfg)
    cfg=EdgeConfig('https://192.168.1.10','unit','s'*48)
    with pytest.raises(ValueError,match='loopback'):PreviewPublisher(cfg)
    local=PreviewPublisher(EdgeConfig('http://127.0.0.1:9000','unit','s'*48,allow_loopback_http=True))
    assert local.close() and local.sent==0


def test_preview_draws_actual_packet_without_mutating_pixels(packet):
    import cv2
    before=packet.frame.copy()
    data=annotated_jpeg(packet)
    result=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
    assert data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9')
    assert result.shape==before.shape and result.any()
    assert np.array_equal(packet.frame,before)


def test_model_metadata_uses_actual_classes_and_does_not_include_errors():
    values=model_metadata({'weapons':{'model_id':'publisher/model','model_version':'revision',
        'classes':['Knife','Pistol'],'status':'active','device':'mps','error':'Private internal path'},
        'unused':{'status':'disabled','error':''}})
    assert values==[{'model_id':'publisher/model','version':'revision','classes':['Knife','Pistol'],'status':'active','device':'mps'}]


@pytest.mark.parametrize('state',['idle','reconnecting','error'])
def test_inactive_heartbeat_keeps_provenance_without_active_model_or_throughput(packet,state):
    from sentinal.connected.monitor import heartbeat_payload
    model={'weapons':{'model_id':'publisher/model','model_version':'revision','classes':['Knife'],'status':'active','device':'mps'}}
    health,cameras,models=heartbeat_payload(state,'unit-camera','Authorized test source',packet,[1.,2.],model)
    assert health=={'status':state}
    assert cameras[0]['last_frame_at']==packet.timestamp
    assert cameras[0]['status']!='running'
    assert models[0]['status']=='idle' and models[0]['version']=='revision'
    running,_,active=heartbeat_payload('running','unit-camera','Authorized test source',packet,[1.,2.],model)
    assert running['processing_fps']==1 and running['inference_ms']==packet.inference_ms
    assert active[0]['status']=='active'
