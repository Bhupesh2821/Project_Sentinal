# Sourced by SENTINAL scripts after setting PROJECT_DIR.
export YOLO_CONFIG_DIR="$PROJECT_DIR/config/runtime/ultralytics"
export MPLCONFIGDIR="$PROJECT_DIR/config/runtime/matplotlib"
export XDG_CONFIG_HOME="$PROJECT_DIR/config/runtime/xdg"
export XDG_DATA_HOME="$PROJECT_DIR/work/runtime-data"
export XDG_CACHE_HOME="$PROJECT_DIR/work/cache/xdg"
export TORCH_HOME="$PROJECT_DIR/work/cache/torch"
export PIP_CACHE_DIR="$PROJECT_DIR/work/pip-cache"
export PYTHONPYCACHEPREFIX="$PROJECT_DIR/work/cache/python"
export TMPDIR="$PROJECT_DIR/work/tmp"
export TEMP="$TMPDIR"
export TMP="$TMPDIR"
export YOLO_AUTOINSTALL=false
export YOLO_OFFLINE=true
mkdir -p "$YOLO_CONFIG_DIR" "$MPLCONFIGDIR" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_CACHE_HOME" "$TORCH_HOME" "$PIP_CACHE_DIR" "$PYTHONPYCACHEPREFIX" "$TMPDIR"
