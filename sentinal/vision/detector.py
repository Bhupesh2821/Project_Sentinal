"""Offline pretrained object detector with supported Ultralytics ByteTrack integration."""
from dataclasses import replace
import logging
import os
from pathlib import Path
from threading import RLock
from time import perf_counter

from ..core.device_manager import select_device, synchronize
from ..config import ROOT
from .tracker import detections_from_result, reset_model_trackers
from .raw_tracking import RawTrackerBank
from .types import FOCUS_CLASSES
from .object_catalog import canonical_label, allowed_class_ids

log = logging.getLogger(__name__)


class DetectorError(RuntimeError):
    pass


class YOLODetector:
    def __init__(self, config):
        self.config = config
        self.model = None
        self.device = "cpu"
        self.last_inference_ms = 0.0
        self.fallback_reason = None
        self._lock = RLock()
        self._track_offset = 0
        self._maximum_track_id = -1
        self._allowed_ids = None
        self._tracking = RawTrackerBank()

    def load(self):
        with self._lock:
            if self.model is not None:
                return self
            weights = Path(self.config.weights)
            if not weights.is_file():
                raise DetectorError("Model weights are missing. Run install.command to install the supported local models.")
            try:
                # Missing dependencies must produce an error, not trigger pip online.
                os.environ.setdefault("YOLO_AUTOINSTALL", "false")
                import ultralytics
                from ultralytics import YOLO
                settings = getattr(ultralytics, "settings", None)
                local_settings = {
                    "sync": False,
                    "datasets_dir": str(ROOT / "data/datasets"),
                    "weights_dir": str(ROOT / "models"),
                    "runs_dir": str(ROOT / "recordings/runs"),
                }
                if settings is not None and any(settings.get(k) != v for k, v in local_settings.items()):
                    settings.update(local_settings)
                self.device = select_device(self.config.device)
                model = YOLO(str(weights), task="detect")
                raw_names = model.names.values() if isinstance(model.names, dict) else model.names
                names = {canonical_label(name) for name in raw_names}
                self._allowed_ids = allowed_class_ids(model.names)
                if not FOCUS_CLASSES.issubset(names):
                    raise DetectorError("The selected model does not support person, backpack, handbag and suitcase classes.")
                self.model = model
                log.info("Loaded local model %s; selected device %s", weights.name, self.device)
            except DetectorError:
                raise
            except Exception as exc:
                log.exception("Model loading failed")
                raise DetectorError("The local detection model could not load. Check installation and diagnostic logs.") from exc
        return self

    def reset_tracking(self, source_id=None):
        with self._lock:
            if self.model is not None:
                reset_model_trackers(self.model)
            self._tracking.reset(source_id)
            self._track_offset = 0
            self._maximum_track_id = -1

    def _run(self, frame):
        # Prediction is independent of track confirmation. The association
        # adapter attaches IDs later and never removes fresh boxes.
        return self.model.predict(
            source=frame, mode="predict", conf=0.05,
            iou=0.7, imgsz=self.config.image_size, device=self.device,
            verbose=False, save=False, stream=False, classes=self._allowed_ids,
        )[0]

    def infer(self, frame, confidence=None, source_id="default"):
        import math
        import numpy as np
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
            raise ValueError("Inference requires a nonempty BGR image with three channels")
        threshold = self.config.confidence if confidence is None else float(confidence)
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("Confidence must be between zero and one")
        with self._lock:
            self.load()
            started = perf_counter()
            try:
                synchronize(self.device)
                result = self._run(frame)
                synchronize(self.device)
            except Exception as exc:
                if self.device != "mps":
                    log.exception("CPU inference failed")
                    raise DetectorError("Detection failed. Check the local model and diagnostic log.") from exc
                self.fallback_reason = f"MPS operation failed ({type(exc).__name__}); switched to CPU"
                log.warning(self.fallback_reason, exc_info=True)
                # Keep the same loaded weights. A predictor rebuild is needed
                # because its AutoBackend otherwise retains the old device.
                self.device = "cpu"
                self._track_offset = self._maximum_track_id + 1
                try:
                    self.model.to("cpu")
                    self.model.predictor = None
                    result = self._run(frame)
                except Exception as cpu_exc:
                    log.exception("CPU fallback inference failed")
                    raise DetectorError("Both MPS and CPU detection failed. See the diagnostic log.") from cpu_exc
            ids = self._tracking.associate(result, frame, source_id) if hasattr(result, "boxes") else None
            detections = detections_from_result(result, frame.shape, threshold, ids)
            if self._track_offset:
                detections = tuple(replace(d, track_id=d.track_id + self._track_offset)
                                   if d.track_id is not None else d for d in detections)
            ids = [d.track_id for d in detections if d.track_id is not None]
            if ids:
                self._maximum_track_id = max(self._maximum_track_id, max(ids))
            self.last_inference_ms = (perf_counter() - started) * 1000
            return detections
