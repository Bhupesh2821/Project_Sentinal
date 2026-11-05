"""Bounded asynchronous local notifications; no external recipient is configured."""
from collections import deque
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
import queue
import threading
from typing import Protocol

@dataclass(frozen=True)
class Notification:
    incident_id:str
    source_id:str
    title:str
    body:str
    severity:int
    confidence:float
    created_at:str

@dataclass(frozen=True)
class Delivery:
    incident_id:str
    channel:str
    delivered:bool
    detail:str
    def to_dict(self):return asdict(self)

class NotificationAdapter(Protocol):
    name:str
    def deliver(self,notification:Notification)->Delivery:...

class InApplicationAdapter:
    name='in_application'
    def __init__(self,callback):self.callback=callback
    def deliver(self,notification):
        self.callback(notification)
        return Delivery(notification.incident_id,self.name,True,'Emitted to local application')

class UnconfiguredExternalAdapter:
    """Explicitly unavailable email/mobile extension; never makes network calls."""
    def __init__(self,name):
        if name not in {'email','mobile_push','desktop'}:raise ValueError('Unknown notification extension')
        self.name=name
    def deliver(self,notification):
        return Delivery(notification.incident_id,self.name,False,'Unavailable: no authorized provider is configured')

class AlertDispatcher:
    def __init__(self,adapters=(),capacity=64):
        if type(capacity) is not int or not 1<=capacity<=1024:raise ValueError('Alert queue capacity must be 1 to 1024')
        self.adapters=tuple(adapters);self._queue=queue.Queue(maxsize=capacity)
        self._stop=threading.Event();self._lock=threading.Lock();self._thread=None
        self._seen=deque(maxlen=1024);self.deliveries=deque(maxlen=1024);self.dropped=0
    def start(self):
        with self._lock:
            if self._thread is None:
                self._thread=threading.Thread(target=self._run,name='SENTINAL local alert delivery',daemon=True);self._thread.start()
        return self
    def publish(self,incident):
        if incident.status!='ALERTED' or self._stop.is_set():return False
        key=incident.incident_id
        notification=Notification(key,incident.source_id,incident.title,'AI candidate awaiting human verification. Confidence is not proof of danger or criminal intent.',incident.severity,incident.confidence,incident.alerted_at or datetime.now(timezone.utc).isoformat())
        with self._lock:
            if key in self._seen:return False
            try:self._queue.put_nowait(notification)
            except queue.Full:self.dropped+=1;return False
            self._seen.append(key)
        self.start();return True
    def _run(self):
        while not self._stop.is_set() or not self._queue.empty():
            try:item=self._queue.get(timeout=.05)
            except queue.Empty:continue
            try:
                for adapter in self.adapters:
                    try:delivery=adapter.deliver(item)
                    except Exception as exc:delivery=Delivery(item.incident_id,getattr(adapter,'name','unknown'),False,'Delivery failed ('+type(exc).__name__+')')
                    with self._lock:self.deliveries.append(delivery)
            finally:self._queue.task_done()
    def take_deliveries(self):
        with self._lock:
            result=tuple(self.deliveries);self.deliveries.clear()
        return result
    @property
    def pending(self):return self._queue.qsize()
    def close(self,timeout=2.0):
        self._stop.set()
        if self._thread is not None:self._thread.join(timeout)
        return self._thread is None or not self._thread.is_alive()
