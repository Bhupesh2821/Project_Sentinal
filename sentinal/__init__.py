"""SENTINAL MARK-007 Vision Core. Keep runtime data beside project source."""
import os
from pathlib import Path
import sys
import tempfile

_ROOT = Path(__file__).resolve().parents[1]
_runtime = _ROOT / "config/runtime"
_LOCAL_PATHS = {
    "YOLO_CONFIG_DIR": _runtime / "ultralytics",
    "MPLCONFIGDIR": _runtime / "matplotlib",
    "XDG_CONFIG_HOME": _runtime / "xdg",
    "XDG_DATA_HOME": _ROOT / "work/runtime-data",
    "XDG_CACHE_HOME": _ROOT / "work/cache/xdg",
    "TORCH_HOME": _ROOT / "work/cache/torch",
    "PIP_CACHE_DIR": _ROOT / "work/pip-cache",
    "PYTHONPYCACHEPREFIX": _ROOT / "work/cache/python",
    "TMPDIR": _ROOT / "work/tmp",
    "TEMP": _ROOT / "work/tmp",
    "TMP": _ROOT / "work/tmp",
}
for _name, _path in _LOCAL_PATHS.items():
    _path.mkdir(parents=True, exist_ok=True)
    os.environ[_name] = str(_path)
os.environ["YOLO_OFFLINE"] = "true"
os.environ["YOLO_AUTOINSTALL"] = "false"
tempfile.tempdir = str(_LOCAL_PATHS["TMPDIR"])
sys.pycache_prefix = str(_LOCAL_PATHS["PYTHONPYCACHEPREFIX"])
__version__ = "0.3.1"
