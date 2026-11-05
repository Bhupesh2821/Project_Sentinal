"""Single-source Vision Core. No Qt or persistence dependency."""
from time import perf_counter
from pathlib import Path
from uuid import uuid4

from .detector import YOLODetector
from .performance import PerformanceMeter
from .types import FOCUS_CLASSES, FramePacket, utc_now
from .object_catalog import safety_tool_label
from .video_source import VideoSource, VideoSourceError


class VisionPipeline:
    def __init__(self, config):
        self.config = config
        self.detector = YOLODetector(config)
        self.performance = PerformanceMeter()
        self.source = None
        self.session_id = ""
        self.hazard_suite = None
        self._hazard_options = {}
        self._hazard_signature = None
        self._last_hazard_time = None

    def configure_hazards(self, enabled=(), confidence=.6, image_size=640, sample_interval_s=.2, detect_fire=True, detect_smoke=True, category_thresholds=None):
        signature=(tuple(enabled),float(confidence),int(image_size),bool(detect_fire),bool(detect_smoke),tuple(sorted((category_thresholds or {}).items())))
        if signature != self._hazard_signature:
            if not enabled:
                if self.hazard_suite is not None:self.hazard_suite.close()
                self.hazard_suite=None
            else:
                options=dict(enabled=tuple(enabled),confidence=confidence,image_size=image_size,detect_fire=detect_fire,detect_smoke=detect_smoke,category_thresholds=dict(category_thresholds or {}))
                if self.hazard_suite is None:
                    from .specialized import SpecializedSuite
                    self.hazard_suite=SpecializedSuite(device=self.config.device,**options)
                else:self.hazard_suite.configure(**options)
            self._hazard_signature=signature
            self._last_hazard_time=None
        self._hazard_options={'sample_interval_s':float(sample_interval_s)}

    def start(self, spec):
        self.stop()
        self.detector.load()
        self.detector.reset_tracking()
        if spec.kind in {"camera", "stream"}:
            from .live_capture import LiveVideoSource
            source = LiveVideoSource(
                spec, self.config.camera_width, self.config.camera_height,
                open_timeout_ms=self.config.stream_open_timeout_ms,
                read_timeout_ms=self.config.stream_read_timeout_ms,
            )
        else:
            source = VideoSource(spec, self.config.camera_width, self.config.camera_height)
        source.open()
        self.source = source
        self.session_id = str(uuid4())
        self.performance.reset()
        self._last_hazard_time=None
        if self.hazard_suite is not None:self.hazard_suite.reset_tracking()
        return self.session_id

    def step(self, confidence=None, focus_only=False, category_filter="all"):
        if category_filter not in {"all", "focus", "safety"}:
            raise ValueError("Unknown category filter")
        if self.source is None:
            raise VideoSourceError("Start a monitoring session before requesting frames.")
        started = perf_counter()
        frame = self.source.read()
        decode_ms=(perf_counter()-started)*1000
        if frame is None:
            return None
        detections = self.detector.infer(frame, confidence)
        if focus_only or category_filter == "focus":
            detections = tuple(d for d in detections if d.label in FOCUS_CLASSES)
        elif category_filter == "safety":
            detections = tuple(d for d in detections if safety_tool_label(d.label))
        hazards=();sampled=False;health={};hazard_ms=0.0
        position=self.source.source_time_s
        interval=self._hazard_options.get('sample_interval_s',.2)
        if self.hazard_suite is not None:
            if self._last_hazard_time is None or position<self._last_hazard_time or position-self._last_hazard_time+1e-6>=interval:
                from time import perf_counter as clock
                hazard_started=clock()
                hazards=self.hazard_suite.infer(frame,frame_index=self.source.frame_index,source_time_s=position,source_id=self.session_id)
                hazard_ms=(clock()-hazard_started)*1000
                sampled=True;self._last_hazard_time=position
            health=dict(self.hazard_suite.health)
        self.performance.record(perf_counter()-started,self.detector.last_inference_ms+hazard_ms)
        return FramePacket(
            frame=frame, detections=detections, session_id=self.session_id,
            source=self.source.description, frame_index=self.source.frame_index,
            timestamp=utc_now(), source_time_s=self.source.source_time_s,
            fps=self.performance.fps, inference_ms=self.detector.last_inference_ms+hazard_ms,
            average_inference_ms=self.performance.average_inference_ms,
            device=self.detector.device,
            frame_age_ms=(getattr(self.source, "frame_age_ms", 0.0)+self.detector.last_inference_ms+hazard_ms
                          if self.source.spec.kind in {"camera", "stream"} else 0.0),
            dropped_frames=getattr(self.source, "dropped_frames", 0),
            model_name=Path(self.config.model_path).name,
            hazards=tuple(hazards),hazard_sampled=sampled,detector_health=health,
            diagnostics={"decode_read_ms":decode_ms,"base_inference_ms":self.detector.last_inference_ms,"hazard_inference_ms":hazard_ms},
        )

    def seek(self, seconds):
        """Seek a local file and create a fresh track/session boundary."""
        if self.source is None or self.source.spec.kind != "file":
            raise VideoSourceError("Seeking is available only for an open local video.")
        actual = self.source.seek(seconds)
        self.detector.reset_tracking()
        self._last_hazard_time=None
        if self.hazard_suite is not None:self.hazard_suite.reset_tracking()
        self.session_id = str(uuid4())
        self.performance.reset()
        return actual

    def stop(self):
        if self.source is not None:
            self.source.close()
            self.source = None

    def reset(self):
        """Restart current source with a new session and fresh tracking identities."""
        if self.source is None:
            raise VideoSourceError("There is no source to restart.")
        return self.start(self.source.spec)
