# Licensing and third-party notices

SENTINAL source is provided under AGPL-3.0, in alignment with its Ultralytics integration. See LICENSE. This is a development source distribution; dependencies retain their own licenses and notices.

- Ultralytics 8.4.183 and YOLO11n COCO weights: AGPL-3.0 / separate Ultralytics Enterprise terms. This deliverable uses the open-source route, with full source supplied. [Official license](https://github.com/ultralytics/ultralytics/blob/main/LICENSE), [model documentation](https://docs.ultralytics.com/models/yolo11/).
- ByteTrack original algorithm/repository: MIT. The implementation used here is the one distributed within Ultralytics under its package terms. [Original ByteTrack](https://github.com/FoundationVision/ByteTrack).
- PyTorch/torchvision: BSD-style licenses. [PyTorch license](https://github.com/pytorch/pytorch/blob/main/LICENSE).
- OpenCV: Apache-2.0 for current OpenCV; opencv-python packaging MIT plus bundled binary third-party notices. [Package](https://pypi.org/project/opencv-python/).
- PySide6/Qt for Python: LGPLv3/GPLv3 or commercial terms; dynamically installed official wheels. [Qt licensing](https://doc.qt.io/qtforpython-6/licenses.html).
- NumPy BSD, SciPy BSD, Pillow MIT-CMU, pytest MIT, lap BSD-2-Clause, and other transitive dependency licenses remain with their authors. Exact installed versions are recorded in requirements-lock.txt.

Public test asset provenance is recorded in docs/FIXTURES.md. Images are not claimed as SENTINAL intellectual property. Model weights are pinned by SHA256 in models/yolo11n.sha256; this pin records the actual downloaded official asset, not an independent signature.


V0.1.2 also includes official Ultralytics YOLOv8n and YOLOv8s Open Images V7 weights under the Ultralytics AGPL-3.0 / separate Enterprise terms. Its 601 raw object labels are documented by the [official Open Images V7 model documentation](https://docs.ultralytics.com/datasets/detect/open-images-v7/); SENTINAL permits a reduced catalog and records model provenance. The installed file checksum is recorded in models/yolov8n-oiv7.sha256 and models/yolov8s-oiv7.sha256. No full training dataset was installed. Public Open Images verification assets retain their original creators' rights; their dataset URLs and annotations are evidence, not a claim that SENTINAL owns those images.


## V0.2 specialized detectors and fixtures

Selected weights and the complete license texts are included under `models/v02/`. `MODEL_MANIFEST.json` and `docs/MODEL_MANIFEST_V02.md` record publisher revisions, exact class maps, download URLs and SHA256 hashes.

- GingerBrains/object-detection YOLOv8s checkpoint: GPL-3.0 repository containing both checkpoint and license at the pinned revision. SENTINAL remains AGPL-3.0 with full source. Generic Gun is never asserted to be a handgun/rifle; Grenade outputs are excluded. Training-data provenance is publisher-reported, not independently audited.
- luminous0219/fire-and-smoke-detection-yolov8 YOLOv8n checkpoint: AGPL-3.0 repository checkpoint, fire/smoke classes.
- Demonstration images/videos retain their original public-domain/Creative Commons/other documented terms. See `docs/FIXTURES_V02.md` and adjacent source records. Derived repeated-still videos are identified explicitly, with no embedded predictions.
- The short alert tone was generated locally as sine-wave audio for this application; no microphone recording or third-party music was used.
- Optional test-only RTSP tools under `work/v02-network-tools` are not application dependencies and are excluded from the portable archive. Their own tool-provenance file records MediaMTX/FFmpeg source and license details.

Rejected/unclear experimental assets are not selected by the runtime or included as application models in the portable archive. Public source distribution does not replace a deployment-specific review of model/data and dependency obligations.


## V0.2.1 optional everyday detector and reported-item fixtures

Optional official Ultralytics YOLO11s COCO weights use the same AGPL-3.0 / separate Enterprise route as YOLO11n. The pinned v8.4.0 asset is documented in models/yolo11s.source.json and its published GitHub asset SHA256 is checked before installation/packaging. Its80 classes add model capacity, not new categories, firearm identification or loose-blade capability. See docs/DETECTION_RELIABILITY_V021.md for measured regressions as well as improvements.

Seven public reported-item photos and approximate annotations are distributed by explicit hashed allowlist in data/v021-items/DISTRIBUTION_MANIFEST.json. See docs/FIXTURES_V021.md for creator credits, source links, respective CC BY/CC BY-SA licenses and transformations. Public test assets remain subject to their individual licenses; no private camera media enters this set.
