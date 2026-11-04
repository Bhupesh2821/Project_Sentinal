"""Conservative accelerator selection; operation failures are handled by detector."""
import logging

log = logging.getLogger(__name__)


def select_device(preference="auto", torch_module=None):
    if preference not in {"auto", "cpu", "mps"}:
        raise ValueError("Device must be auto, cpu or mps")
    if preference == "cpu":
        return "cpu"
    if torch_module is None:
        import torch as torch_module
    mps = getattr(getattr(torch_module, "backends", None), "mps", None)
    try:
        available = bool(mps is not None and mps.is_available())
    except Exception:
        log.warning("MPS capability query failed; selecting CPU", exc_info=True)
        available = False
    if preference == "mps" and not available:
        log.warning("MPS requested but unavailable; selecting CPU")
    return "mps" if available else "cpu"


def synchronize(device, torch_module=None):
    """Make elapsed MPS inference measurements include completed GPU work."""
    if device == "mps":
        if torch_module is None:
            import torch as torch_module
        torch_module.mps.synchronize()
