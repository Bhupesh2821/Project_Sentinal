"""Explicit loopback-only, memory-only annotated video previews."""
import base64
from datetime import datetime, timezone
import ipaddress
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request
from .edge import EdgeConfig, HTTPTransport
from .protocol import PREVIEW_PATH, canonical_json, sign_request, strict_json, text


def annotated_jpeg(packet):
    """Draw actual provided observations on their exact source pixels."""
    import cv2
    frame = packet.frame.copy()
    h, w = frame.shape[:2]
    for item, hazard in [(d, False) for d in packet.detections] + [(d, True) for d in packet.hazards]:
        a,b,c,d = (int(round(value)) for value in item.bbox)
        color = (80,185,235) if hazard else (245,165,85)
        cv2.rectangle(frame, (max(0,a),max(0,b)), (min(w-1,c),min(h-1,d)), color, 2)
        name = ('Possible ' + item.category.replace('weapon_','').replace('_',' ')) if hazard else item.label
        label = name + f' {item.confidence:.0%}' + (f' #{item.track_id}' if item.track_id is not None else '')
        cv2.putText(frame,label,(max(0,a),max(15,b-6)),cv2.FONT_HERSHEY_SIMPLEX,.45,color,1,cv2.LINE_AA)
    cv2.putText(frame,'Analyzed '+packet.timestamp,(8,h-10),cv2.FONT_HERSHEY_SIMPLEX,.38,(230,240,250),1,cv2.LINE_AA)
    scale = min(1.,640/w,480/h)
    if scale < 1:
        frame = cv2.resize(frame,(max(1,round(w*scale)),max(1,round(h*scale))))
    ok, output = cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,70])
    if not ok or len(output) > 393216:
        raise ValueError('The bounded JPEG preview could not be encoded')
    return bytes(output)


class PreviewPublisher(threading.Thread):
    """A latest-frame mailbox. Never enters the persistent event outbox.

    Only an explicitly selected loopback backend may receive preview bytes.
    Internet/public Base44 endpoints cannot be configured for this local mode.
    """
    def __init__(self,config,rate=2):
        super().__init__(name='sentinal-local-preview',daemon=True)
        if not isinstance(config,EdgeConfig):raise ValueError('Use validated edge preferences')
        if config.ingest_path!='/api/edge/events':raise ValueError('Video preview is unavailable on the cloud event gateway')
        try:local=ipaddress.ip_address(urlsplit(config.server_url).hostname).is_loopback
        except ValueError:local=False
        if not local:raise ValueError('Video preview delivery is restricted to an explicit loopback backend')
        if type(rate) not in (int,float) or not .2<=rate<=5:raise ValueError('Preview rate must be .2 to 5 frames per second')
        self.config=config;self.rate=rate;self._lock=threading.Lock();self._latest=None
        self._stop_event=threading.Event();self._wake=threading.Event()
        self.sent=0;self.dropped=0;self.last_error=''
    def submit(self,packet,camera_id):
        text(camera_id,'Camera ID',128)
        if not self.is_alive() or self._stop_event.is_set():return False
        with self._lock:
            if self._latest is not None:self.dropped+=1
            self._latest=(packet,camera_id)
        self._wake.set();return True
    def request_stop(self):
        self._stop_event.set()
        with self._lock:self._latest=None
        self._wake.set()
    def close(self,timeout=5):
        self.request_stop()
        if self.ident is not None:self.join(timeout)
        return not self.is_alive()
    def run(self):
        transport=HTTPTransport(self.config);last=0.
        while not self._stop_event.is_set():
            remaining=1/self.rate-(time.monotonic()-last)
            if remaining>0:
                self._stop_event.wait(remaining)
                continue
            with self._lock:value,self._latest=self._latest,None
            if value is None:self._wake.wait(.2);self._wake.clear();continue
            packet,camera=value
            try:
                age=time.time()-datetime.fromisoformat(packet.timestamp).timestamp()
                if age>2.5 or age< -1:self.dropped+=1;continue
                body=canonical_json({'device_id':self.config.device_id,'camera_id':camera,
                    'captured_at':packet.timestamp,'jpeg_base64':base64.b64encode(annotated_jpeg(packet)).decode('ascii')})
                headers=sign_request(self.config.secret,self.config.device_id,body,path=PREVIEW_PATH)
                headers['Content-Type']='application/json'
                request=Request(self.config.server_url.rstrip('/')+PREVIEW_PATH,data=body,headers=headers,method='POST')
                with transport.opener.open(request,timeout=self.config.request_timeout_s) as response:
                    ack=strict_json(response.read(8193))
                if not isinstance(ack,dict) or ack.get('ok') is not True or ack.get('camera_id')!=camera:
                    raise ValueError('Invalid preview acknowledgment')
                self.sent+=1;self.last_error=''
            except HTTPError as exc:
                self.last_error=f'Local preview rejected (HTTP {exc.code})';exc.close()
            except (ValueError,OSError,URLError,TypeError):
                self.last_error='Local preview is unavailable; no frames are saved'
            finally:last=time.monotonic()
