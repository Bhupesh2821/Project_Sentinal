"""Future authorized physical-sensor interfaces. No synthetic live readings."""
from dataclasses import dataclass
import math
from typing import Protocol
from .incidents import validate_timestamp

class SensorUnavailable(RuntimeError):pass

@dataclass(frozen=True)
class SensorReading:
    sensor_id:str
    kind:str
    value:float
    unit:str
    timestamp:str
    def __post_init__(self):
        if not self.sensor_id or self.kind not in {'smoke','gas','temperature','fire_alarm','chemical'}:raise ValueError('Invalid physical sensor metadata')
        if type(self.value) not in (int,float) or not math.isfinite(self.value):raise ValueError('A real finite sensor reading is required')
        validate_timestamp(self.timestamp)

class SensorAdapter(Protocol):
    kind:str
    @property
    def available(self)->bool:...
    def read(self)->SensorReading:...
    def close(self)->None:...

class UnavailableSensor:
    def __init__(self,kind):
        if kind not in {'smoke','gas','temperature','fire_alarm','chemical'}:raise ValueError('Unknown future sensor type')
        self.kind=kind
    @property
    def available(self):return False
    def read(self):raise SensorUnavailable('No authorized '+self.kind+' sensor hardware is connected')
    def close(self):return None

class SensorRegistry:
    def __init__(self):self.adapters={}
    def register(self,sensor_id,adapter):
        if not sensor_id or sensor_id in self.adapters:raise ValueError('Unique sensor ID required')
        self.adapters[sensor_id]=adapter
    def status(self):return tuple({'sensor_id':key,'kind':adapter.kind,'available':bool(adapter.available)} for key,adapter in self.adapters.items())
    def read(self,sensor_id,authorized=False):
        if not authorized:raise PermissionError('Physical sensor access requires authorized configuration')
        adapter=self.adapters[sensor_id]
        if not adapter.available:raise SensorUnavailable('Physical sensor unavailable')
        return adapter.read()
    def close(self):
        for adapter in self.adapters.values():adapter.close()
