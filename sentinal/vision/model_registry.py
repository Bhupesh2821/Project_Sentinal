"""Pinned local V0.2 assets. Runtime never downloads or installs dependencies."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
from sentinal.config import ROOT

@dataclass(frozen=True)
class ModelAsset:
    key: str
    filename: str
    model_id: str
    version: str
    source_url: str
    license: str
    sha256: str

    @property
    def path(self): return ROOT / 'models/v02' / self.filename

# Filled from bytes obtained from the pinned publisher revisions. No unknown
# checksum or license is accepted by runtime model loading.
ASSETS = {
    'fire_smoke': ModelAsset('fire_smoke','fire_smoke.pt','luminous0219/fire-and-smoke-yolov8n','c30923f568d915a53fcf85989be9fe5d4e030518','https://raw.githubusercontent.com/luminous0219/fire-and-smoke-detection-yolov8/c30923f568d915a53fcf85989be9fe5d4e030518/weights/best.pt','AGPL-3.0','ac0a10257b2bc1f20c9d957f8adeeb61dd6140322fc19d0b4a116cb491776d16'),
    'weapons': ModelAsset('weapons','weapon_ginger.pt','GingerBrains/YOLOv8s-weapons','ab6f53c8d18d77d799fa70a46adea646d7bb4499','https://raw.githubusercontent.com/GingerBrains/object-detection/ab6f53c8d18d77d799fa70a46adea646d7bb4499/best.pt','GPL-3.0 repository checkpoint; Ultralytics AGPL-3.0 integration','a010e4a9a18f9b1ccaffe063334f088d5b64083e4ccd7b9ef2dbc7b183fc2d80'),
}

def verify_asset(asset):
    if not asset.path.is_file():
        raise ValueError('Local detector weights are unavailable. Run tools/download_v02_models.py during installation.')
    with asset.path.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    if len(asset.sha256) != 64 or digest != asset.sha256:
        raise ValueError('The local detector checksum is unverified or mismatched. Reinstall the pinned model.')
    return asset.path
