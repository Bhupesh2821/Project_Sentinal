"""Offline model catalogs and category policy; never a database of identities."""
from dataclasses import dataclass
import json
from pathlib import Path

from sentinal.config import ROOT


@dataclass(frozen=True)
class ModelProfile:
    key: str
    title: str
    model_path: str
    catalog_filename: str


MODEL_PROFILES = (
    ModelProfile("everyday", "Everyday objects · YOLO11n", "models/yolo11n.pt", "yolo11n.json"),
    ModelProfile("extended", "Extended objects · lightweight", "models/yolov8n-oiv7.pt", "yolov8n-oiv7.json"),
    ModelProfile("extended_small", "Extended objects · higher capacity", "models/yolov8s-oiv7.pt", "yolov8n-oiv7.json"),
    ModelProfile("everyday_small", "Everyday objects · higher detail (COCO)", "models/yolo11s.pt", "yolo11n.json"),
)

# The Open Images weights also contain age/gender/body-part categories. They
# are deliberately never requested from inference or retained as detections.
_EXCLUDED = frozenset({"boy", "girl", "man", "woman", "bomb", "handgun", "missile", "rifle", "shotgun", "tank", "weapon"})
_SAFETY_TOOLS = frozenset({"axe", "bicycle helmet", "boot", "drill (tool)", "flashlight", "glove", "goggles", "hammer", "helmet", "ladder", "nail (construction)", "personal flotation device", "scissors", "screwdriver", "tool", "wrench"})
_ALIASES = {"drill (tool)": "drill", "nail (construction)": "construction nail"}


def canonical_label(label):
    """Normalize model spelling while preserving each class's actual meaning."""
    name = " ".join(str(label).strip().lower().split())
    return _ALIASES.get(name, name)


def label_allowed(label):
    name = " ".join(str(label).strip().lower().split())
    return bool(name) and name not in _EXCLUDED and not name.startswith("human ")


_SAFETY_CANONICAL = frozenset(canonical_label(n) for n in _SAFETY_TOOLS)


def safety_tool_label(label):
    return canonical_label(label) in _SAFETY_CANONICAL


def allowed_class_ids(names, group="all"):
    """Return model-native IDs; IDs must never be shared between model families."""
    if group not in {"all", "safety", "focus"}:
        raise ValueError("Unknown category filter")
    entries = names.items() if isinstance(names, dict) else enumerate(names)
    allowed = []
    for class_id, name in entries:
        if not label_allowed(name):
            continue
        label = canonical_label(name)
        if group == "safety" and not safety_tool_label(name):
            continue
        if group == "focus" and label not in {"person", "backpack", "handbag", "suitcase"}:
            continue
        allowed.append(int(class_id))
    return sorted(allowed)


def profile_for_model(model_path):
    name = Path(model_path).name
    return next((p for p in MODEL_PROFILES if Path(p.model_path).name == name), None)


def catalog_rows(model_path, group="all"):
    """Read the installed catalog without loading PyTorch/weights on the UI."""
    profile = profile_for_model(model_path)
    if profile is None:
        return ()
    path = ROOT / "docs/catalogs" / profile.catalog_filename
    if not path.is_file():
        return ()
    data = json.loads(path.read_text())
    names = {int(k): v for k, v in data["names"].items()}
    return tuple({"id": i, "label": canonical_label(names[i]), "model_label": names[i],
                  "safety_tool": safety_tool_label(names[i])}
                 for i in allowed_class_ids(names, group))
