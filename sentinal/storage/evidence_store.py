"""Explicit opt-in, owner-only snapshots. No camera pixels are saved by default."""
from datetime import datetime,timedelta,timezone
import hashlib
import os
from pathlib import Path
import re
from uuid import uuid4
from sentinal.config import ROOT
from .incident_database import project_path

class EvidenceStore:
    encryption='No application-layer encryption; local account file permissions'
    def __init__(self,path=None,retention_days=7,max_bytes=256*1024*1024,max_files=1000):
        self.path=project_path(path or ROOT/'recordings/incidents/evidence')
        if type(retention_days) is not int or not 1<=retention_days<=365:raise ValueError('Evidence retention must be 1 to 365 days')
        if type(max_bytes) is not int or not 1024*1024<=max_bytes<=2*1024**3:raise ValueError('Evidence capacity must be 1 MB to 2 GB')
        if type(max_files) is not int or not 1<=max_files<=10000:raise ValueError('Evidence count must be 1 to 10000')
        self.retention_days=retention_days;self.max_bytes=max_bytes;self.max_files=max_files;self.owner_uid=os.getuid()
    def _files(self):
        if not self.path.exists():return []
        if self.path.stat().st_uid!=self.owner_uid:raise PermissionError('Evidence folder belongs to a different account')
        return sorted((p for p in self.path.iterdir() if re.fullmatch(r'[0-9a-f]{32}\.jpg',p.name) and not p.is_symlink() and p.is_file() and p.stat().st_uid==self.owner_uid),key=lambda p:p.stat().st_mtime)
    def prune(self):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=self.retention_days)).timestamp()
        removed=[];files=self._files()
        for path in list(files):
            if path.stat().st_mtime<cutoff:path.unlink();removed.append(path.name);files.remove(path)
        total=sum(p.stat().st_size for p in files)
        while files and (len(files)>self.max_files or total>self.max_bytes):
            path=files.pop(0);total-=path.stat().st_size;path.unlink();removed.append(path.name)
        return removed
    def save_snapshot(self,incident,frame,enabled=False):
        if not enabled:return None
        if os.getuid()!=self.owner_uid:raise PermissionError('Only the current local account may save evidence')
        if getattr(incident,'status',None) not in {'ALERTED','ACKNOWLEDGED','VERIFIED'}:raise ValueError('Snapshots are limited to alert/review incidents')
        import cv2
        import numpy as np
        if not isinstance(frame,np.ndarray) or frame.dtype!=np.uint8 or frame.ndim!=3 or frame.shape[2]!=3 or not frame.size:raise ValueError('Snapshot requires an actual BGR image')
        height,width=frame.shape[:2]
        if max(height,width)>8192:raise ValueError('Evidence frame is too large')
        image=frame
        if max(height,width)>1920:
            scale=1920/max(height,width);image=cv2.resize(frame,(max(1,round(width*scale)),max(1,round(height*scale))))
        ok,encoded=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,88])
        if not ok:raise OSError('Evidence image could not be encoded')
        data=encoded.tobytes()
        if len(data)>2*1024*1024 or len(data)>self.max_bytes:raise ValueError('Encoded evidence exceeds its storage limit')
        self.path.mkdir(parents=True,exist_ok=True);self.path.chmod(0o700);self.prune()
        files=self._files();total=sum(p.stat().st_size for p in files)
        while files and (len(files)>=self.max_files or total+len(data)>self.max_bytes):
            old=files.pop(0);total-=old.stat().st_size;old.unlink()
        target=self.path/(uuid4().hex+'.jpg');partial=target.with_suffix('.part')
        try:
            descriptor=os.open(partial,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'wb') as output:output.write(data);output.flush();os.fsync(output.fileno())
            partial.replace(target)
        finally:partial.unlink(missing_ok=True)
        return {'path':str(target),'sha256':hashlib.sha256(data).hexdigest(),'width':image.shape[1],'height':image.shape[0],'source_width':width,'source_height':height}
    def resolve(self,value,sha256=None):
        path=project_path(ROOT/value if not Path(value).is_absolute() else value)
        if not path.is_relative_to(self.path) or path.is_symlink() or not path.is_file() or path.stat().st_uid!=self.owner_uid:raise PermissionError('Evidence is unavailable or outside the private store')
        if path.stat().st_size>2*1024*1024:raise ValueError('Evidence file is too large')
        if sha256 is not None and hashlib.sha256(path.read_bytes()).hexdigest()!=sha256:raise ValueError('Evidence integrity check failed')
        return path
