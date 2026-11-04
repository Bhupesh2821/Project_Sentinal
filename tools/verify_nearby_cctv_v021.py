"""Actual bounded LAN discovery and native loopback-list/batch-selection checks.

--lan sends only standard camera discovery multicast, with no sign-in or video.
The native test uses a clearly identified controlled UDP advertiser on localhost.
"""
from pathlib import Path
import argparse,hashlib,json,socket,sys,threading,time
from datetime import datetime,timezone
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sentinal.vision import network_discovery as discovery


def sha(value):return hashlib.sha256(value.encode()).hexdigest()

def reply(message_id):
    matches=''.join(f'<d:ProbeMatch><a:EndpointReference><a:Address>urn:uuid:fixture-{index}</a:Address></a:EndpointReference><d:Types>dn:NetworkVideoTransmitter</d:Types><d:Scopes>onvif://www.onvif.org/name/Fixture%20{title}</d:Scopes><d:XAddrs>http://127.0.0.1:{18080+index}/onvif/device_service</d:XAddrs></d:ProbeMatch>' for index,title in enumerate(('Door','Hall')))
    return f'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"><s:Header><a:RelatesTo>{message_id}</a:RelatesTo></s:Header><s:Body><d:ProbeMatches>{matches}</d:ProbeMatches></s:Body></s:Envelope>'.encode()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--lan',action='store_true');args=parser.parse_args()
    output=ROOT/'docs/evidence/v021-2026-11-02';output.mkdir(parents=True,exist_ok=True)
    report={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'camera_capture_opened':False,'physical_cctv_verified':False}
    if args.lan:
        report['scope']='Actual local-network standard ONVIF discovery; no camera authentication or frames, identities hashed'
        report['active_interfaces']=[{'name':i.name,'address_sha256':sha(i.address)} for i in discovery.discovery_interfaces()]
        started=time.monotonic()
        try:
            cameras=discovery.discover_cameras(timeout_s=3.)
            report.update(discovery_call_completed=True,advertisements_received=len(cameras),camera_names_sha256=[sha(c.name) for c in cameras],endpoint_sha256=[sha(c.device_url) for c in cameras])
        except discovery.NetworkCameraError as exc:report.update(discovery_call_completed=False,error=str(exc))
        report['elapsed_s']=time.monotonic()-started
        report['limitation']='No reply does not prove no cameras exist; ONVIF discovery, local-network permission, selected interface and isolation affect results. Advertisements do not prove sign-in or video health.'
        (output/'nearby-real-lan.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0 if report['discovery_call_completed'] else 1
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from sentinal.interface.network_camera_dialog import NetworkCameraDialog
    from sentinal.interface.camera_manager_dialog import CameraManagerDialog
    from sentinal.interface.themes import STYLESHEET
    from sentinal.storage.camera_registry import CameraRegistry
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLESHEET)
    report.update(scope='Native Qt UI, actual controlled localhost UDP advertisements, actual local registry/batch selection; not physical CCTV',checks={},passed=False)
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    def wait(predicate,seconds=6):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            app.processEvents()
            if predicate():return
            time.sleep(.004)
        raise AssertionError('Native discovery transition timed out')
    factory=socket.socket;server=factory(socket.AF_INET,socket.SOCK_DGRAM);server.bind(('127.0.0.1',0));server.settimeout(.1)
    stop=threading.Event();received=[]
    def respond():
        while not stop.is_set():
            try:data,address=server.recvfrom(65535)
            except socket.timeout:continue
            except OSError:return
            message=discovery.children_named(ET.fromstring(data),'MessageID')[0].text
            received.append(True);server.sendto(reply(message),address)
    responder=threading.Thread(target=respond,daemon=True);responder.start()
    class ControlledSocket:
        def __init__(self,*a,**k):self.socket=factory(*a,**k)
        def __enter__(self):return self
        def __exit__(self,*args):self.socket.close()
        def __getattr__(self,key):return getattr(self.socket,key)
        def sendto(self,data,address):
            if address==('239.255.255.250',3702):return self.socket.sendto(data,server.getsockname())
            return self.socket.sendto(data,address)
    view=NetworkCameraDialog();view.show();app.processEvents();manager=None;registry=None
    try:
        check('no_discovery_before_click',not view.setup_running and not received)
        view.network_combo.addItem('Controlled loopback test','127.0.0.1');view.network_combo.setCurrentIndex(view.network_combo.count()-1)
        discovery.socket.socket=ControlledSocket
        view.discover_button.click();wait(lambda:not view.setup_running)
        check('real_udp_reply_received',len(received)==2)
        check('native_list_has_two_camera_services',view.camera_list.count()==2)
        check('advertised_not_authenticated_status','not yet verified' in view.status.text())
        view.camera_list.setCurrentRow(0);check('selection_fills_device_address',view.address.text().startswith('http://127.0.0.1:'))
        check('no_video_stream_selected',not view.use_button.isEnabled())
        check('native_nearby_screenshot',view.grab().save(str(output/'nearby-loopback.png')))
        view.discover_button.click();wait(lambda:not view.setup_running)
        check('refresh_replaces_and_deduplicates',view.camera_list.count()==2 and len(received)==4)
        registry_path=ROOT/'work/v021-nearby-native/registry.sqlite3';registry_path.parent.mkdir(parents=True,exist_ok=True)
        registry=CameraRegistry(registry_path)
        for title in ('Door','Hall'):
            existing=next((record for record in registry.list_cameras() if record.name=='Fixture '+title),None)
            registry.upsert_network('Fixture '+title,'rtsp://127.0.0.1:18554/'+title.lower(),camera_id=existing.camera_id if existing else None)
        manager=CameraManagerDialog(registry=registry);manager.show();app.processEvents();selected=[];manager.cameras_selected.connect(selected.append)
        for row in range(manager.table.rowCount()):manager.table.item(row,0).setCheckState(Qt.CheckState.Checked)
        check('native_checked_camera_screenshot',manager.grab().save(str(output/'checked-cameras-loopback.png')))
        check('batch_requires_explicit_use',not selected)
        manager.use_checked_button.click();app.processEvents()
        check('two_camera_selections_returned',len(selected)==1 and len(selected[0])==2)
        check('manager_never_started_capture',not manager.setup_running and all(record.connection_health=='idle' for record in registry.list_cameras()))
        report['passed']=all(report['checks'].values())
    except Exception as exc:report['failure']=str(exc)
    finally:
        discovery.socket.socket=factory
        view.cancel_setup();view.wait_for_setup();view.close()
        if manager is not None:manager.cancel_setup();manager.wait_for_setup();manager.close()
        if registry is not None:registry.close()
        stop.set();server.close();responder.join(1);app.processEvents()
        report['responder_released']=not responder.is_alive();report['passed']=report['passed'] and report['responder_released']
        (output/'nearby-native-loopback.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
