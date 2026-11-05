"""Attach ByteTrack IDs without discarding fresh detector predictions.

Ultralytics track() returns only tracker-confirmed rows in some frames. This
adapter uses supported BYTETracker.update() and its original detection index,
leaving raw source-pixel boxes/confidences untouched. IDs remain optional.
"""
from collections import OrderedDict
from types import SimpleNamespace
import logging
import numpy as np

log=logging.getLogger(__name__)


def _array(value):
    if hasattr(value,'detach'):value=value.detach()
    if hasattr(value,'cpu'):value=value.cpu()
    return np.asarray(value,dtype=np.float32)


class RawTrackerBank:
    def __init__(self,max_sources=8):
        if type(max_sources) is not int or not 1<=max_sources<=32:raise ValueError('Tracking source limit must be1–32')
        self.max_sources=max_sources;self._trackers=OrderedDict();self._failed={}
    def _source(self,source_id):
        if not isinstance(source_id,str) or not source_id or len(source_id)>256 or any(ord(c)<32 for c in source_id):raise ValueError('A readable bounded source ID is required')
        return source_id
    def status(self,source_id='default'):
        return 'unavailable' if source_id in self._failed else 'active' if source_id in self._trackers else 'idle'
    def reset(self,source_id=None):
        if source_id is None:self._trackers.clear();self._failed.clear()
        else:self._trackers.pop(self._source(source_id),None);self._failed.pop(source_id,None)
    def _tracker(self,source_id):
        if source_id in self._trackers:self._trackers.move_to_end(source_id);return self._trackers[source_id]
        from ultralytics.trackers.byte_tracker import BYTETracker
        args=SimpleNamespace(track_high_thresh=.25,track_low_thresh=.1,new_track_thresh=.25,track_buffer=30,match_thresh=.8,fuse_score=True)
        while len(self._trackers)>=self.max_sources:
            old,_=self._trackers.popitem(last=False);self._failed.pop(old,None)
        tracker=BYTETracker(args);self._trackers[source_id]=tracker;return tracker
    def associate(self,result,frame,source_id='default'):
        source_id=self._source(source_id)
        if source_id in self._failed:return {}
        try:
            from ultralytics.engine.results import Boxes
            boxes=getattr(result,'boxes',None)
            if boxes is None:data=np.empty((0,6),dtype=np.float32)
            else:
                xyxy=_array(boxes.xyxy).reshape(-1,4);scores=_array(boxes.conf).reshape(-1);classes=_array(boxes.cls).reshape(-1)
                if not len(xyxy)==len(scores)==len(classes):raise ValueError('Inconsistent raw detection arrays')
                data=np.column_stack((xyxy,scores,classes))
            valid=np.all(np.isfinite(data),axis=1)&(data[:,2]>data[:,0])&(data[:,3]>data[:,1])&(data[:,4]>=0)&(data[:,4]<=1)&(data[:,5]>=0)&(data[:,5]==np.floor(data[:,5]))
            original_indices=np.flatnonzero(valid)
            rows=self._tracker(source_id).update(Boxes(data[valid],frame.shape[:2]),frame)
            assigned={}
            for row in rows:
                track,local_index=float(row[4]),float(row[-1])
                if np.isfinite(track) and track>=0 and int(track)==track and np.isfinite(local_index) and int(local_index)==local_index and 0<=int(local_index)<len(original_indices):
                    assigned[int(original_indices[int(local_index)])]=int(track)
            return assigned
        except Exception:
            # Tracking is an association aid. A failure must not erase model
            # evidence or imply that an object disappeared.
            log.exception('Raw prediction tracking failed; retaining detections without IDs')
            self._failed[source_id]=True
            while len(self._failed)>self.max_sources:self._failed.pop(next(iter(self._failed)))
            return {}
