"""Sample metadata at a bounded cadence, always opt-in for each run."""
import logging
import time
from sentinal.config import ROOT
from sentinal.storage.database import DetectionDatabase

log = logging.getLogger(__name__)


def format_event(packet, detection):
    return {
        'timestamp': packet.timestamp, 'session_id': packet.session_id,
        'source': packet.source, 'frame_index': packet.frame_index,
        'model_name': getattr(packet, 'model_name', ''),
        'source_time_s': packet.source_time_s,
        'category': detection.label, 'class_id': detection.class_id,
        'confidence': detection.confidence, 'track_id': detection.track_id,
        'track_key': f'{packet.session_id}:{detection.track_id}' if detection.track_id is not None else None,
        'bbox': list(detection.bbox), 'fps': packet.fps,
        'inference_ms': packet.inference_ms, 'device': packet.device,
    }


class EventManager:
    def __init__(self, config, path=None, clock=time.monotonic):
        self.config = config
        self.path = path or ROOT / 'recordings/detections.sqlite3'
        self.clock = clock
        self.database = None
        self.last_sample = None
        self.session_id = None

    def process(self, packet, enabled=False):
        """Return a user-facing error or None. Never abort monitoring for storage."""
        if not enabled:
            self.close()
            return None
        now = self.clock()
        if packet.session_id != self.session_id:
            self.last_sample = None
            self.session_id = packet.session_id
        if self.last_sample is not None and now - self.last_sample < self.config.sample_interval_s:
            return None
        try:
            if self.database is None:
                self.database = DetectionDatabase(self.path, self.config.retention_days, self.config.max_detection_rows)
            self.database.record(packet)
            self.last_sample = now
        except Exception:
            log.exception('Local metadata recording failed')
            self.close()
            return 'Metadata could not be saved. Recording has been disabled; monitoring can continue. Check storage space and folder permissions.'
        return None

    def close(self):
        if self.database is not None:
            try:
                self.database.close()
            except Exception:
                log.exception('Could not close metadata database')
        self.database = None
        self.last_sample = None
