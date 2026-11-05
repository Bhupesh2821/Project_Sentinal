"""Actual deployed-cloud retry/replay checks reuse a genuine saved model alert.
No new synthetic incidents are inserted. Device credentials remain owner-local.
"""
from pathlib import Path
import json,sys
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler
from urllib.error import HTTPError
import ssl
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sentinal.connected.edge import EdgeConfig,incident_event
from sentinal.connected.protocol import canonical_json,sign_request

def main():
    config=EdgeConfig.load(ROOT/'config/connected/base44-edge.json')
    source=json.loads((ROOT/'docs/evidence/v03-2026-11-03/base44-edge-weapon.json').read_text())
    event=incident_event(source['alerts'][0],config.device_id);body=canonical_json(event)
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=ssl.create_default_context()))
    report={'test':'Actual Base44 duplicate retry, nonce replay and changed-body conflict using a real previously delivered model alert','checks':{},'passed':False,'frames_uploaded':False}
    def send(raw,headers):
        request=Request(config.endpoint,data=raw,headers={'Content-Type':'application/json',**headers},method='POST')
        try:
            with opener.open(request,timeout=10) as response:return response.status,json.loads(response.read(131073))
        except HTTPError as exc:return exc.code,json.loads(exc.read(131073))
    try:
        headers=sign_request(config.secret,config.device_id,body)
        status,value=send(body,headers);report['checks']['same_real_event_fresh_nonce_acknowledged_once']=status==200 and value.get('duplicate') is True
        status,_=send(body,headers);report['checks']['used_nonce_rejected']=status==409
        changed=json.loads(body);changed['incident']['confidence']=.51
        raw=canonical_json(changed);status,_=send(raw,sign_request(config.secret,config.device_id,raw))
        report['checks']['same_event_id_changed_body_rejected']=status==409
        report['passed']=all(report['checks'].values())
    except Exception as exc:report['failure']=type(exc).__name__
    output=ROOT/'docs/evidence/v03-2026-11-03/base44-replay.json';output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
