"""ONVIF protocol regression with a real loopback SOAP server, not CCTV hardware."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from urllib.request import parse_http_list, parse_keqv_list

import pytest

from sentinal.vision.network_discovery import (
    NetworkCameraError, parse_probe_matches, validated_device_url, parse_xml,
    make_probe, discover_cameras, children_named,
)
from sentinal.vision.onvif_client import OnvifClient, DEVICE_NS, MEDIA_NS, MEDIA2_NS


def envelope(body):
    return ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:t="http://www.onvif.org/ver10/media/wsdl" '
            'xmlns:tt="http://www.onvif.org/ver10/schema"><s:Body>' + body +
            '</s:Body></s:Envelope>').encode()


@pytest.fixture
def camera_server():
    state = SimpleNamespace(auth=True, digest=False, redirect=False, slow=False, drip=False, fault=False,
                            media2=False, challenges=0, actions=[], wsse_valid=[], active=0)
    username, password = 'test-camera-account', 'TestOnly-S3cret-NotReal'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            state.active += 1
            try:
                request = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                if state.redirect:
                    self.send_response(307); self.send_header('Location', 'http://other.invalid/onvif'); self.end_headers(); return
                authorization = self.headers.get('Authorization', '')
                authorized = authorization == 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode()
                challenge = 'Basic realm="TestCamera"'
                if state.digest:
                    challenge = 'Digest realm="TestCamera", nonce="test-only-nonce-abc", algorithm=MD5, qop="auth"'
                    authorized = False
                    if authorization.startswith('Digest '):
                        values = parse_keqv_list(parse_http_list(authorization[7:]))
                        md5 = lambda data: hashlib.md5(data.encode()).hexdigest()
                        ha1 = md5(f'{username}:TestCamera:{password}')
                        ha2 = md5(f'POST:{values.get("uri", "")}')
                        expected_response = md5(f'{ha1}:test-only-nonce-abc:{values.get("nc", "")}:{values.get("cnonce", "")}:auth:{ha2}')
                        authorized = values.get('response') == expected_response and values.get('username') == username and values.get('uri') == self.path
                if state.auth and not authorized:
                    state.challenges += 1
                    self.send_response(401); self.send_header('WWW-Authenticate', challenge); self.end_headers(); return
                if state.slow:
                    time.sleep(.4)
                root = ET.fromstring(request)
                operation = list(children_named(root, 'Body')[0])[0].tag.rsplit('}', 1)[-1]
                state.actions.append(operation)
                nonce, created, digest = [children_named(root, n)[0].text for n in ('Nonce', 'Created', 'Password')]
                expected = base64.b64encode(hashlib.sha1(base64.b64decode(nonce) + created.encode() + password.encode()).digest()).decode()
                state.wsse_valid.append(digest == expected and password.encode() not in request)
                address = f'http://127.0.0.1:{self.server.server_port}/onvif/media'
                if state.fault:
                    body = '<s:Fault><s:Reason>PRIVATE-FAULT-TEXT-TestOnly-S3cret-NotReal</s:Reason></s:Fault>'
                elif operation == 'GetCapabilities':
                    body = '<GetCapabilitiesResponse/>' if state.media2 else f'<GetCapabilitiesResponse><Media><XAddr>{address}</XAddr></Media></GetCapabilitiesResponse>'
                elif operation == 'GetServices':
                    body = f'<GetServicesResponse><Service><Namespace>{MEDIA2_NS}</Namespace><XAddr>{address}</XAddr></Service></GetServicesResponse>'
                elif operation == 'GetProfiles':
                    body = '<t:GetProfilesResponse><t:Profiles token="main"><tt:Name>Main stream</tt:Name><tt:VideoEncoderConfiguration><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>1280</tt:Width><tt:Height>720</tt:Height></tt:Resolution></tt:VideoEncoderConfiguration></t:Profiles></t:GetProfilesResponse>'
                elif operation == 'GetStreamUri':
                    body = '<t:GetStreamUriResponse><t:MediaUri><tt:Uri>rtsp://0.0.0.0:8554/private-stream?key=test-only-token</tt:Uri></t:MediaUri></t:GetStreamUriResponse>'
                else:
                    body = '<Unknown/>'
                response = envelope(body)
                self.send_response(200); self.send_header('Content-Type','application/soap+xml'); self.send_header('Content-Length',str(len(response))); self.end_headers()
                try:
                    if state.drip:
                        for value in response:
                            self.wfile.write(bytes([value]));self.wfile.flush();time.sleep(.02)
                    else:
                        self.wfile.write(response)
                except (BrokenPipeError, ConnectionResetError): pass
            finally:
                state.active -= 1
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    state.url = f'http://127.0.0.1:{server.server_port}/onvif/device_service'
    state.username, state.password = username,password
    yield state
    server.shutdown(); server.server_close(); thread.join(timeout=2)
    assert not thread.is_alive()


def test_real_loopback_soap_basic_challenge_wsse_and_stream(camera_server):
    s = camera_server
    client = OnvifClient(s.url,s.username,s.password,timeout_s=1)
    result = client.list_streams()
    assert len(result) == 1
    stream = result[0]
    assert stream.uri == 'rtsp://127.0.0.1:8554/private-stream?key=test-only-token'
    assert (stream.width,stream.height,stream.encoding)==(1280,720,'H264')
    assert s.actions == ['GetCapabilities','GetProfiles','GetStreamUri']
    assert s.challenges == 3 and all(s.wsse_valid)
    assert all(secret not in repr(client)+repr(stream)+stream.description for secret in (s.password,'test-only-token','private-stream'))
    assert s.active == 0


def test_real_loopback_media2_service_fallback(camera_server):
    s=camera_server; s.media2=True
    streams=OnvifClient(s.url,s.username,s.password,timeout_s=1).list_streams()
    assert len(streams)==1 and 'GetServices' in s.actions


def test_real_loopback_bad_password_is_redacted(camera_server):
    s=camera_server
    with pytest.raises(NetworkCameraError) as caught:
        OnvifClient(s.url,s.username,'Wrong-Private-Password',timeout_s=1).list_streams()
    assert 'sign-in failed' in str(caught.value)
    assert 'Wrong-Private-Password' not in str(caught.value)


def test_real_loopback_redirect_does_not_forward_credentials(camera_server):
    s=camera_server; s.redirect=True
    with pytest.raises(NetworkCameraError,match='redirected'):
        OnvifClient(s.url,s.username,s.password,timeout_s=1).list_streams()
    assert not s.actions


def test_real_loopback_fault_does_not_expose_response_body(camera_server):
    s=camera_server; s.fault=True
    with pytest.raises(NetworkCameraError) as caught:
        OnvifClient(s.url,s.username,s.password,timeout_s=1).list_streams()
    assert 'PRIVATE-FAULT' not in str(caught.value) and s.password not in str(caught.value)


def test_real_loopback_read_timeout_is_bounded_and_redacted(camera_server):
    s=camera_server; s.slow=True
    started=time.monotonic()
    with pytest.raises(NetworkCameraError):
        OnvifClient(s.url,s.username,s.password,timeout_s=.2).list_streams()
    assert time.monotonic()-started<2


@pytest.mark.parametrize('value',['http://u:secret@192.0.2.2/onvif','ftp://192.0.2.2/x','http://host:0/x','http://host/x?secret=1','http://host/\npath','http://host:bad/x'])
def test_device_url_rejection_never_echoes_input(value):
    with pytest.raises(NetworkCameraError) as caught: validated_device_url(value)
    assert value not in str(caught.value)


def test_device_default_path_and_cross_host_guard():
    assert validated_device_url('http://192.0.2.2')=='http://192.0.2.2/onvif/device_service'
    client=OnvifClient('https://192.0.2.2/onvif')
    with pytest.raises(NetworkCameraError,match='different server'): client._endpoint('https://192.0.2.3/onvif')
    with pytest.raises(NetworkCameraError,match='insecure'): client._endpoint('http://192.0.2.2/onvif')
    with pytest.raises(NetworkCameraError): client._stream_uri('rtsp://u:secret@192.0.2.2/private')
    with pytest.raises(NetworkCameraError): client._stream_uri('rtsp://192.0.2.3/private')


@pytest.mark.parametrize('data',[b'<!DOCTYPE foo [<!ENTITY x "private">]><foo>&x;</foo>',b'<broken',b'x'*(1024*1024+1),b''])
def test_peer_xml_limits_and_dtd_rejection(data):
    with pytest.raises(NetworkCameraError): parse_xml(data)


def probe_reply(message_id='urn:uuid:test'):
    return f'''<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"><s:Header><a:RelatesTo>{message_id}</a:RelatesTo></s:Header><s:Body><d:ProbeMatches><d:ProbeMatch><a:EndpointReference><a:Address>urn:uuid:camera</a:Address></a:EndpointReference><d:Types>dn:NetworkVideoTransmitter</d:Types><d:Scopes>onvif://www.onvif.org/name/Test%20Camera</d:Scopes><d:XAddrs>http://192.0.2.2/onvif/device_service ftp://bad.invalid/</d:XAddrs></d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>'''.encode()


def test_discovery_reply_validation_and_correlation():
    devices=parse_probe_matches(probe_reply(),'urn:uuid:test')
    assert len(devices)==1 and devices[0].name=='Test Camera'
    assert devices[0].device_url=='http://192.0.2.2/onvif/device_service'
    assert parse_probe_matches(probe_reply(),'urn:uuid:wrong')==[]
    message,request=make_probe()
    assert message.encode() in request and b'NetworkVideoTransmitter' in request


def test_discovery_udp_probe_dedupe_and_cancel(monkeypatch):
    import sentinal.vision.network_discovery as module
    received=[]; sent=[]
    class Socket:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def setsockopt(self,*args):pass
        def settimeout(self,*args):pass
        def bind(self,*args):pass
        def sendto(self,data,address):
            sent.append(address)
            msg=children_named(ET.fromstring(data),'MessageID')[0].text
            received.append(probe_reply(msg))
        def recvfrom(self,*args):
            if received:return received.pop(),('192.0.2.2',3702)
            raise socket.timeout()
    monkeypatch.setattr(module.socket,'socket',lambda *args:Socket())
    devices=discover_cameras(.2)
    assert len(devices)==1 and sent==[('239.255.255.250',3702)]*2
    stop=threading.Event();stop.set();sent.clear()
    assert discover_cameras(.2,stop)==[] and not sent


def test_cancelled_onvif_makes_no_network_connection(monkeypatch):
    import sentinal.vision.onvif_client as module
    stop=threading.Event();stop.set()
    monkeypatch.setattr(module,'build_opener',lambda *args:pytest.fail('Cancelled setup touched network'))
    with pytest.raises(NetworkCameraError,match='cancelled'):
        OnvifClient('http://192.0.2.2',cancel_event=stop).list_streams()


def test_real_loopback_http_digest_authentication(camera_server):
    s=camera_server;s.digest=True
    streams=OnvifClient(s.url,s.username,s.password,timeout_s=1).list_streams()
    assert len(streams)==1 and s.challenges==3 and all(s.wsse_valid)
    assert s.actions==['GetCapabilities','GetProfiles','GetStreamUri']


@pytest.mark.parametrize('encoding',['utf-16','utf-16-le','utf-32'])
def test_peer_xml_entity_cannot_bypass_guard_with_wide_encoding(encoding):
    content='<?xml version="1.0"?><!DOCTYPE root [<!ENTITY x "private-expanded-body">]><root>&x;</root>'
    with pytest.raises(NetworkCameraError):parse_xml(content.encode(encoding))


def test_real_loopback_slow_drip_respects_overall_deadline(camera_server):
    s=camera_server;s.drip=True
    client=OnvifClient(s.url,s.username,s.password,timeout_s=1)
    client._deadline=time.monotonic()+.25
    started=time.monotonic()
    with pytest.raises(NetworkCameraError,match='timed out'):
        client._post(s.url,DEVICE_NS,'GetCapabilities')
    assert time.monotonic()-started<.8


def test_real_loopback_udp_discovery_transport_with_controlled_target(monkeypatch):
    import sentinal.vision.network_discovery as module
    # Only this fixture redirects the multicast destination to a loopback peer.
    # send/receive use real UDP; this does not claim discovery of a physical CCTV.
    factory=socket.socket
    server=factory(socket.AF_INET,socket.SOCK_DGRAM);server.bind(('127.0.0.1',0));server.settimeout(.2)
    stop=threading.Event();replies=[];destinations=[]
    def respond():
        while not stop.is_set():
            try:data,address=server.recvfrom(65535)
            except socket.timeout:continue
            except OSError:return
            message=children_named(ET.fromstring(data),'MessageID')[0].text
            server.sendto(probe_reply(message),address);replies.append(True)
    thread=threading.Thread(target=respond,daemon=True);thread.start()
    class ControlledSocket:
        def __init__(self,*args):self.socket=factory(*args)
        def __enter__(self):return self
        def __exit__(self,*args):self.socket.close()
        def __getattr__(self,key):return getattr(self.socket,key)
        def sendto(self,data,target):
            destinations.append(target)
            assert target==('239.255.255.250',3702)
            return self.socket.sendto(data,server.getsockname())
    monkeypatch.setattr(module.socket,'socket',ControlledSocket)
    try:
        devices=discover_cameras(.3)
        assert len(devices)==1 and devices[0].name=='Test Camera'
        assert replies and destinations==[('239.255.255.250',3702)]*2
    finally:
        stop.set();server.close();thread.join(timeout=1)
    assert not thread.is_alive()
