"""Validated V0.2 preferences. Recording and sound require runtime opt-in."""
from dataclasses import asdict, dataclass, field, fields
import json
import math
from pathlib import Path
from sentinal.config import ROOT

def _finite_number(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except (OverflowError,ValueError):return False

@dataclass(frozen=True)
class V02Settings:
    detectors: tuple = ('weapons','fire_smoke')
    detect_fire: bool = True
    detect_smoke: bool = True
    confidence: float = .6
    display_confidence: float = .25
    category_thresholds: dict = field(default_factory=dict)
    min_consecutive: int = 3
    persistence_s: float = 1.0
    max_gap_s: float = .75
    cooldown_s: float = 30.0
    sample_interval_s: float = .2
    retention_days: int = 7
    max_incidents: int = 10000
    audio_volume: float = .5
    audio_severity: int = 3
    camera_rules: dict = field(default_factory=dict)

    def __post_init__(self):
        for name in ('detect_fire','detect_smoke'):
            if type(getattr(self,name)) is not bool:raise ValueError('Invalid '+name)
        object.__setattr__(self,'detectors',tuple(self.detectors))
        if len(set(self.detectors))!=len(self.detectors) or not set(self.detectors)<={'weapons','fire_smoke','ghs'}:raise ValueError('Invalid detector modules')
        for name,lo,hi in [('display_confidence',.05,.99),('confidence',.05,.99),('persistence_s',0,60),('max_gap_s',.05,10),('cooldown_s',1,3600),('sample_interval_s',.05,10),('audio_volume',0,1)]:
            value=getattr(self,name)
            if not _finite_number(value) or not lo<=value<=hi:raise ValueError(f'Invalid {name}')
        for name,lo,hi in [('min_consecutive',2,100),('retention_days',1,365),('max_incidents',100,100000),('audio_severity',1,4)]:
            value=getattr(self,name)
            if type(value) is not int or not lo<=value<=hi:raise ValueError(f'Invalid {name}')
        from sentinal.core.incidents import CATEGORIES
        if not isinstance(self.category_thresholds,dict) or not set(self.category_thresholds)<=CATEGORIES:raise ValueError('Invalid category display thresholds')
        if any(not _finite_number(value) or not .05<=value<=.99 for value in self.category_thresholds.values()):raise ValueError('Invalid category display threshold')
        if not isinstance(self.camera_rules,dict):raise ValueError('Invalid camera rules')
        for ident,rule in self.camera_rules.items():
            if not isinstance(ident,str) or not isinstance(rule,dict):raise ValueError('Invalid camera rule')
            from sentinal.core.incidents import TemporalRule
            TemporalRule(**rule)

    @classmethod
    def load(cls,path=None):
        path=Path(path) if path else ROOT/'config/v02.json'
        if not path.exists():return cls()
        values=json.loads(path.read_text())
        if not isinstance(values,dict) or set(values)-{f.name for f in fields(cls)}:raise ValueError('Invalid V0.2 settings')
        return cls(**values)

    def save(self,path=None):
        path=Path(path) if path else ROOT/'config/v02.json'
        if not path.resolve().is_relative_to(ROOT):raise ValueError('Settings must stay inside project')
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix('.part');temporary.write_text(json.dumps(asdict(self),indent=2)+'\n');temporary.chmod(0o600);temporary.replace(path)
