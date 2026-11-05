"""Discovery/multi-selection contracts; component fakes are not hardware proof."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import socket,threading,time
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from sentinal.vision import network_discovery as discovery
from sentinal.interface import network_camera_dialog as network_ui
from sentinal.interface import camera_manager_dialog as manager_ui
from sentinal.storage.camera_registry import CameraRegistry


def spin(app,predicate):
    until=time.monotonic()+3
    while time.monotonic()<until:
        app.processEvents()
        if predicate():return
        time.sleep(.004)
    raise AssertionError('Nearby camera UI timed out')


def reply(message_id,name='Fixture Camera'):
    return f'''<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"><s:Header><a:RelatesTo>{message_id}</a:RelatesTo></s:Header><s:Body><d:ProbeMatches><d:ProbeMatch><a:EndpointReference><a:Address>urn:uuid:nearby-test</a:Address></a:EndpointReference><d:Types>dn:NetworkVideoTransmitter</d:Types><d:Scopes>onvif://www.onvif.org/name/{name.replace(' ','%20')}</d:Scopes><d:XAddrs>http://127.0.0.1/onvif/device_service</d:XAddrs></d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>'''.encode()


def test_interface_enumeration_only_up_nonloopback_ipv4(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil,'net_if_stats',lambda:{'en0':SimpleNamespace(isup=True),'en1':SimpleNamespace(isup=False),'lo0':SimpleNamespace(isup=True)})
    monkeypatch.setattr(psutil,'net_if_addrs',lambda:{'en0':[SimpleNamespace(family=socket.AF_INET,address='192.0.2.5'),SimpleNamespace(family=socket.AF_INET,address='192.0.2.5'),SimpleNamespace(family=socket.AF_INET6,address='fe80::1')],'en1':[SimpleNamespace(family=socket.AF_INET,address='192.0.2.6')],'lo0':[SimpleNamespace(family=socket.AF_INET,address='127.0.0.1')]})
    interfaces=discovery.discovery_interfaces()
    assert interfaces==(discovery.DiscoveryInterface('en0','192.0.2.5'),)
    assert '192.0.2.5' in interfaces[0].description


@pytest.mark.parametrize('address',['bad','::1','0.0.0.0','239.255.255.250','255.255.255.255',4])
def test_invalid_interface_fails_before_network(monkeypatch,address):
    monkeypatch.setattr(discovery.socket,'socket',lambda *a:pytest.fail('Invalid interface opened socket'))
    with pytest.raises(ValueError,match='local IPv4'):discovery.discover_cameras(.2,interface_address=address)


def test_cancelled_discovery_does_not_open_socket(monkeypatch):
    event=threading.Event();event.set()
    monkeypatch.setattr(discovery.socket,'socket',lambda *a:pytest.fail('Cancelled discovery opened socket'))
    assert discovery.discover_cameras(.2,event,interface_address='192.0.2.5')==[]


def test_actual_loopback_selected_interface_udp_and_deduplication(monkeypatch):
    factory=socket.socket
    server=factory(socket.AF_INET,socket.SOCK_DGRAM);server.bind(('127.0.0.1',0));server.settimeout(.1)
    stop=threading.Event();requests=[];binds=[];options=[]
    def respond():
        while not stop.is_set():
            try:data,address=server.recvfrom(65535)
            except socket.timeout:continue
            except OSError:return
            message=discovery.children_named(ET.fromstring(data),'MessageID')[0].text
            requests.append(address)
            server.sendto(reply(message),address);server.sendto(reply(message),address)
    thread=threading.Thread(target=respond,daemon=True);thread.start()
    class ControlledSocket:
        def __init__(self,*args):self.socket=factory(*args)
        def __enter__(self):return self
        def __exit__(self,*args):self.socket.close()
        def __getattr__(self,key):return getattr(self.socket,key)
        def setsockopt(self,*args):options.append(args);return self.socket.setsockopt(*args)
        def bind(self,address):binds.append(address);return self.socket.bind(address)
        def sendto(self,data,address):
            assert address==('239.255.255.250',3702)
            return self.socket.sendto(data,server.getsockname())
    monkeypatch.setattr(discovery.socket,'socket',ControlledSocket)
    try:
        started=time.monotonic();devices=discovery.discover_cameras(.25,interface_address='127.0.0.1')
        assert time.monotonic()-started<1
        assert len(devices)==1 and devices[0].name=='Fixture Camera'
        assert binds==[('127.0.0.1',0)] and len(requests)==2
        assert (socket.IPPROTO_IP,socket.IP_MULTICAST_IF,socket.inet_aton('127.0.0.1')) in options
        assert (socket.IPPROTO_IP,socket.IP_MULTICAST_TTL,1) in options
    finally:
        stop.set();server.close();thread.join(1)
    assert not thread.is_alive()


def test_nearby_list_refresh_uses_selected_network_without_getting_stream(monkeypatch):
    app=QApplication.instance() or QApplication([]);calls=[]
    monkeypatch.setattr(network_ui,'discovery_interfaces',lambda:(discovery.DiscoveryInterface('en0','192.0.2.5'),))
    monkeypatch.setattr(network_ui,'discover_cameras',lambda **kwargs:calls.append(kwargs) or [discovery.NetworkCamera('Door','http://192.0.2.10/onvif')])
    monkeypatch.setattr(network_ui,'OnvifClient',lambda *a,**k:pytest.fail('Discovery tried to authenticate'))
    view=network_ui.NetworkCameraDialog();view.show();app.processEvents()
    try:
        assert not calls
        view.network_combo.setCurrentIndex(1);view.discover_button.click()
        spin(app,lambda:not view.setup_running)
        assert calls[0]['interface_address']=='192.0.2.5'
        assert view.camera_list.count()==1 and 'ONVIF advertised' in view.camera_list.item(0).text()
        assert 'not yet verified' in view.status.text() and not view.use_button.isEnabled()
        view.network_combo.setCurrentIndex(1);view.refresh_networks();assert view.network_combo.currentData()=='192.0.2.5'
    finally:view.close();app.processEvents()


def test_empty_refresh_does_not_claim_no_cameras_exist(monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(network_ui,'discovery_interfaces',lambda:())
    view=network_ui.NetworkCameraDialog()
    view._discovered([])
    assert 'does not prove' in view.status.text()
    view.close();app.processEvents()


def test_checked_saved_cameras_return_explicit_batch_without_capture(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(manager_ui,'discover_cameras',lambda:[])
    monkeypatch.setattr(manager_ui,'LiveVideoSource',lambda *a,**k:pytest.fail('Selection opened a camera'))
    registry=CameraRegistry(tmp_path/'camera-selection/registry.sqlite3')
    first=registry.upsert_network('Door','rtsp://127.0.0.1:8554/door','viewer','OneSecret')
    second=registry.upsert_network('Hall','rtsp://127.0.0.1:8554/hall','viewer','TwoSecret')
    view=manager_ui.CameraManagerDialog(registry=registry);selected=[];view.cameras_selected.connect(selected.append)
    try:
        assert not view.use_checked_button.isEnabled()
        for i in range(2):view.table.item(i,0).setCheckState(Qt.CheckState.Checked)
        view.refresh();assert view._checked_ids=={first.camera_id,second.camera_id}
        assert all(view.table.item(i,0).checkState()==Qt.CheckState.Checked for i in range(2))
        view.use_checked_button.click();app.processEvents()
        assert len(selected)==1 and len(selected[0])==2
        assert {selection.record.camera_id for selection in selected[0]}=={first.camera_id,second.camera_id}
        assert not view.setup_running and 'Secret' not in repr(selected[0])
    finally:view.close();registry.close();app.processEvents()


def test_batch_selection_does_not_partially_emit_expired_credentials(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(manager_ui,'discover_cameras',lambda:[])
    registry=CameraRegistry(tmp_path/'expired-camera-selection/registry.sqlite3')
    registry.upsert_network('Expired','rtsp://127.0.0.1:8554/expired')
    view=manager_ui.CameraManagerDialog(registry=registry);selected=[];view.cameras_selected.connect(selected.append)
    try:
        view.table.item(0,0).setCheckState(Qt.CheckState.Checked);registry.credentials.clear_session()
        view.use_checked();assert not selected and 'cannot be resolved' in view.status.text()
        view.set_monitoring_active(True);assert not view.use_checked_button.isEnabled()
    finally:view.close();registry.close();app.processEvents()


def test_interface_metadata_permission_failure_preserves_manual_route(monkeypatch):
    import psutil
    def denied():raise psutil.AccessDenied()
    monkeypatch.setattr(psutil,'net_if_stats',denied)
    assert discovery.discovery_interfaces()==()
