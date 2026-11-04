"""Persistent inference owner with bounded commands and a latest-packet mailbox."""
from dataclasses import replace
import logging
import math
import queue
import threading
import time
import psutil

from PySide6.QtCore import QThread, Signal

from sentinal.vision.pipeline import VisionPipeline
from sentinal.vision.video_source import VideoSourceError
from sentinal.vision.detector import DetectorError
from sentinal.core.event_manager import EventManager

log = logging.getLogger(__name__)


class InferenceWorker(QThread):
    state_changed = Signal(str, str)
    error = Signal(str)
    metadata_failed = Signal(str)
    playback_changed = Signal(object)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._commands = queue.Queue(maxsize=16)
        self._command_lock = threading.Lock()
        self._shutdown = threading.Event()
        self._stop_requested = threading.Event()
        self._lock = threading.Lock()
        self._latest = None
        self._confidence = config.confidence
        self._focus_only = False
        self._metadata_enabled = False
        self._image_size = config.image_size
        self._model_path = config.model_path
        self._category_filter = "all"
        self._hazard_options={"enabled":()}
        self._incident_consumer=None
        self._diagnostic_time=0.0
        self._process_metrics=None
        self._diagnostic_values={}
        self.pipeline = None
        self._duration_s = None
        self._position_s = 0.0

    def _enqueue(self, command, argument=None):
        with self._command_lock:
            # Coalesce pending slider/pause commands and keep requests bounded.
            pending = []
            while True:
                try:
                    item = self._commands.get_nowait()
                except queue.Empty:
                    break
                if command in {"seek", "pause"} and item[0] == command:
                    continue
                pending.append(item)
            if command in {"stop", "shutdown"}:
                pending = []
            if command == "start":
                pending = [item for item in pending if item[0] not in {"start", "seek", "pause"}]
            for item in pending[-15:]:
                self._commands.put_nowait(item)
            self._commands.put_nowait((command, argument))

    def request_start(self, spec):
        self._enqueue("start", spec)

    def request_stop(self):
        self._stop_requested.set()
        self._enqueue("stop")

    def request_shutdown(self):
        self._shutdown.set()
        self._stop_requested.set()
        self._enqueue("shutdown")

    def request_pause(self, paused=True):
        self._enqueue("pause", bool(paused))

    def request_seek(self, seconds):
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Video position must be a nonnegative number of seconds")
        self._enqueue("seek", seconds)

    def set_options(self, confidence=None, focus_only=None, metadata_enabled=None, image_size=None, model_path=None, category_filter=None):
        if category_filter is not None and category_filter not in {"all", "focus", "safety"}:
            raise ValueError("Unknown category filter")
        if model_path is not None:
            replace(self.config, model_path=model_path)
        with self._lock:
            if model_path is not None:
                self._model_path = model_path
            if category_filter is not None:
                self._category_filter = category_filter
            if confidence is not None:
                self._confidence = confidence
            if focus_only is not None:
                self._focus_only = focus_only
            if metadata_enabled is not None:
                self._metadata_enabled = metadata_enabled
            if image_size is not None:
                if type(image_size) is not int or image_size not in {320, 480, 640, 960}:
                    raise ValueError("Unsupported inference size")
                self._image_size = image_size

    def set_hazard_options(self,enabled=(),confidence=.6,image_size=640,sample_interval_s=.2,detect_fire=True,detect_smoke=True,category_thresholds=None):
        from sentinal.core.v02_settings import V02Settings
        V02Settings(detectors=tuple(enabled),display_confidence=confidence,category_thresholds=dict(category_thresholds or {}),sample_interval_s=sample_interval_s,detect_fire=detect_fire,detect_smoke=detect_smoke)
        if image_size not in (320,480,640,960):raise ValueError('Invalid hazard inference size')
        with self._lock:
            self._hazard_options={'enabled':tuple(enabled),'confidence':confidence,'image_size':image_size,'sample_interval_s':sample_interval_s,'detect_fire':detect_fire,'detect_smoke':detect_smoke,'category_thresholds':dict(category_thresholds or {})}

    def set_incident_consumer(self,consumer=None):
        with self._lock:self._incident_consumer=consumer

    def take_latest(self):
        with self._lock:
            packet, self._latest = self._latest, None
            return packet

    def _playback(self, enabled=True):
        source = getattr(self.pipeline, "source", None)
        fps = getattr(source, "fps", 0)
        count = getattr(source, "frame_count", 0)
        is_file = getattr(getattr(source, "spec", None), "kind", None) == "file"
        if is_file and fps > 0 and count > 0:
            self._duration_s = count / fps
        if source is not None:
            self._position_s = getattr(source, "source_time_s", self._position_s)
        self.playback_changed.emit({"duration_s": self._duration_s, "position_s": self._position_s,
                                    "can_seek": bool(enabled and is_file and fps > 0 and count > 1)})

    def _publish(self, packet, events, metadata):
        metadata_error = events.process(packet, enabled=metadata)
        if metadata_error:
            with self._lock:
                self._metadata_enabled = False
            events.close()
            self.metadata_failed.emit(metadata_error)
        if time.monotonic()-self._diagnostic_time>=1:
            try:
                if self._process_metrics is None:self._process_metrics=psutil.Process()
                self._diagnostic_values['memory_rss_mb']=self._process_metrics.memory_info().rss/(1024*1024)
                self._diagnostic_values['cpu_percent']=self._process_metrics.cpu_percent(None) if self._diagnostic_time else None
                self._diagnostic_time=time.monotonic()
            except Exception:pass
        packet.diagnostics.update(self._diagnostic_values)
        with self._lock:consumer=self._incident_consumer
        if consumer is not None and getattr(packet,'hazard_sampled',False):
            consumer(packet)
        with self._lock:
            self._latest = packet
        self._position_s = packet.source_time_s
        self._playback()

    def _apply_size(self, image_size):
        detector = getattr(self.pipeline, "detector", None)
        current = getattr(detector, "config", None)
        if current is not None and current.image_size != image_size:
            detector.config = replace(current, image_size=image_size)
            self.pipeline.config = replace(self.pipeline.config, image_size=image_size)

    def run(self):
        active = paused = preview_once = False
        spec = None
        events = None
        reconnects = 0
        last_position_s = None
        try:
            events = EventManager(self.config)
            while not self._shutdown.is_set():
                try:
                    command, argument = self._commands.get(timeout=0 if active and not paused else .1)
                except queue.Empty:
                    command, argument = None, None
                if command == "shutdown":
                    break
                if command == "stop":
                    if self.pipeline is not None:
                        self.pipeline.stop()
                    events.close()
                    active = paused = preview_once = False
                    with self._lock:
                        self._latest = None
                    self._playback(enabled=False)
                    self.state_changed.emit("stopped", "Monitoring stopped · source released")
                elif command == "start":
                    self._stop_requested.clear()
                    self.state_changed.emit("loading", "Opening source and loading local vision model…")
                    try:
                        events.close()
                        with self._lock:
                            next_config = replace(self.config, model_path=self._model_path, image_size=self._image_size)
                        current_config = getattr(self.pipeline, "config", self.config)
                        if self.pipeline is not None and current_config.model_path != next_config.model_path:
                            self.pipeline.stop()
                            self.pipeline = None
                        if self.pipeline is None:
                            self.pipeline = VisionPipeline(next_config)
                        self.pipeline.stop()
                        self.pipeline.start(argument)
                        spec = argument
                        active, paused, preview_once = True, False, False
                        reconnects = 0
                        last_position_s = None
                        self._duration_s, self._position_s = None, 0.0
                        with self._lock:
                            self._latest = None
                        self._playback()
                        if not self._stop_requested.is_set() and not self._shutdown.is_set():
                            self.state_changed.emit("running", "Monitoring · local inference active")
                    except Exception as exc:
                        active = False
                        if self.pipeline is not None:
                            self.pipeline.stop()
                        events.close()
                        if not self._stop_requested.is_set() and not self._shutdown.is_set():
                            self._report_failure(exc)
                elif command == "pause" and active and spec.kind == "file":
                    paused = argument
                    if paused:
                        events.close()
                    self.state_changed.emit("paused" if paused else "running",
                                            "Video paused" if paused else "Monitoring · local inference active")
                elif command == "seek" and active and spec.kind == "file":
                    try:
                        events.close()
                        self.pipeline.seek(argument)
                        last_position_s = None
                        preview_once = True
                        with self._lock:
                            self._latest = None
                        self._playback()
                    except VideoSourceError:
                        self.error.emit("This video could not seek to that position. Playback can continue.")
                        log.warning("Video decoder rejected a seek operation")
                if not active or self._stop_requested.is_set() or (paused and not preview_once):
                    continue
                try:
                    frame_started = time.monotonic()
                    with self._lock:
                        confidence, focus, metadata, size = self._confidence, self._focus_only, self._metadata_enabled, self._image_size
                        category_filter = self._category_filter
                        hazard_options=dict(self._hazard_options)
                    self._apply_size(size)
                    if hasattr(self.pipeline,"configure_hazards"):
                        self.pipeline.configure_hazards(**hazard_options)
                    step_options = {"confidence": confidence, "focus_only": focus}
                    if category_filter != "all":
                        step_options["category_filter"] = category_filter
                    packet = self.pipeline.step(**step_options)
                    preview_once = False
                    if packet is None:
                        self._playback(enabled=False)
                        self.pipeline.stop()
                        events.close()
                        active = paused = False
                        self.state_changed.emit("eof", "Video complete · press Replay video to restart")
                        continue
                    if self._stop_requested.is_set() or self._shutdown.is_set():
                        continue
                    reconnects = 0
                    self._publish(packet, events, metadata)
                    if spec.kind == "file" and not paused:
                        fps = getattr(getattr(self.pipeline, "source", None), "fps", 0)
                        interval = 1 / fps if fps > 0 else 0.0
                        if last_position_s is not None:
                            media_delta = packet.source_time_s - last_position_s
                            if math.isfinite(media_delta) and media_delta > 0:
                                interval = media_delta
                        if interval > 0:
                            self._stop_requested.wait(max(0, interval - (time.monotonic() - frame_started)))
                    last_position_s = packet.source_time_s
                except Exception as exc:
                    self.pipeline.stop()
                    events.close()
                    with self._lock:
                        self._latest = None
                    if self._stop_requested.is_set() or self._shutdown.is_set():
                        continue
                    if spec is not None and spec.kind == "stream" and reconnects < self.config.stream_reconnect_attempts:
                        recovered = False
                        while reconnects < self.config.stream_reconnect_attempts:
                            reconnects += 1
                            self.state_changed.emit("reconnecting", f"Feed interrupted · reconnecting {reconnects}/{self.config.stream_reconnect_attempts}…")
                            if self._stop_requested.wait(min(10.0,self.config.stream_reconnect_delay_s*(2**(reconnects-1)))) or self._shutdown.is_set():
                                break
                            try:
                                self.pipeline.start(spec)
                                recovered = True
                                self.state_changed.emit("running", "Feed reconnected · fresh tracking session")
                                self._playback()
                                break
                            except Exception:
                                self.pipeline.stop()
                                log.warning("Network feed reconnect attempt failed")
                        if recovered or self._stop_requested.is_set() or self._shutdown.is_set():
                            continue
                    active = paused = False
                    self._playback(enabled=False)
                    self._report_failure(exc)
        except Exception as exc:
            self._report_failure(exc)
        finally:
            if self.pipeline is not None:
                self.pipeline.stop()
            if events is not None:
                events.close()
            if self.pipeline is not None and getattr(self.pipeline,"hazard_suite",None) is not None:self.pipeline.hazard_suite.close()

    def _report_failure(self, error):
        log.exception("Vision worker failed")
        message = str(error).strip() if isinstance(error, (VideoSourceError, DetectorError)) else "Vision processing stopped unexpectedly. See the diagnostic log, then try starting again."
        self.state_changed.emit("error", "Monitoring unavailable · source released")
        self.error.emit(message)
