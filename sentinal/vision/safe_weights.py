"""Restricted deserialization for pinned, reviewed V0.2 PyTorch assets.

No arbitrary publisher GLOBAL is imported. The reviewed classes are installed
PyTorch/Ultralytics modules only. No unrestricted pickle or dill is used.
"""
import importlib

_ALLOWED = frozenset("""
torch.nn.modules.conv.Conv2d torch.nn.modules.container.Sequential
torch.nn.modules.container.ModuleList torch.nn.modules.upsampling.Upsample
torch.nn.modules.pooling.MaxPool2d torch.nn.modules.batchnorm.BatchNorm2d
torch.nn.modules.activation.SiLU torch.nn.modules.linear.Identity
ultralytics.nn.tasks.DetectionModel ultralytics.nn.modules.conv.Conv
ultralytics.nn.modules.conv.Concat ultralytics.nn.modules.conv.DWConv
ultralytics.nn.modules.block.SPPF ultralytics.nn.modules.block.C2f
ultralytics.nn.modules.block.DFL ultralytics.nn.modules.block.Bottleneck
ultralytics.nn.modules.block.Attention ultralytics.nn.modules.block.C3k2
ultralytics.nn.modules.block.PSABlock ultralytics.nn.modules.block.C2PSA
ultralytics.nn.modules.block.C3k ultralytics.nn.modules.head.Detect
""".split())


_ALIASES = {
    'ultralytics.nn.modules.'+name: 'ultralytics.nn.modules.'+name
    for name in ('Concat','C2f','Detect','Conv','SPPF','DFL','Bottleneck')
}
_ALIASES['ultralytics.yolo.utils.IterableSimpleNamespace'] = 'ultralytics.utils.IterableSimpleNamespace'


def _legacy_set(name):
    if name != 'set':
        raise ValueError('Unreviewed legacy serialization type')
    return set


def load_pinned_yolo(asset):
    from .model_registry import verify_asset
    path = verify_asset(asset)
    import torch
    from ultralytics import YOLO
    from ultralytics.utils import DEFAULT_CFG_DICT
    names = torch.serialization.get_unsafe_globals_in_checkpoint(path)
    permitted = []
    for name in names:
        if name == 'dill._dill._load_type' and asset.key == 'fire_smoke':
            permitted.append((_legacy_set, name))
        elif name in _ALIASES and asset.key == 'weapons':
            module, _, attribute = _ALIASES[name].rpartition('.')
            permitted.append((getattr(importlib.import_module(module), attribute), name))
        elif name in _ALLOWED:
            module, _, attribute = name.rpartition('.')
            permitted.append(getattr(importlib.import_module(module), attribute))
        else:
            raise ValueError('The model contains an unreviewed serialization class')
    with torch.serialization.safe_globals(permitted):
        checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    module = checkpoint.get('ema') or checkpoint['model']
    module = module.float()
    module.args = {**DEFAULT_CFG_DICT, **checkpoint.get('train_args', {}), 'task': 'detect'}
    module.pt_path = str(path)
    module.task = 'detect'
    # Construct only a local architecture shell, then inject the safely loaded
    # module. YOLO(path.pt) would use unrestricted publisher pickle loading.
    wrapper = YOLO('yolov8n.yaml', task='detect', verbose=False)
    wrapper.model = module
    wrapper.ckpt = checkpoint
    wrapper.ckpt_path = str(path)
    wrapper.overrides = {'model': str(path), 'task': 'detect'}
    return wrapper
