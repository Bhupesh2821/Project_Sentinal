# V0.2 specialized model manifest

Prepared November 2, 2026 from pinned local assets and executed evidence. These are experimental visual detectors. Publisher-reported training data and rights have not been independently audited; a small local screening is not field validation. SENTINAL labels every result possible and requires human review.

## Selected checkpoints

Both checkpoints are included beside their original license texts. `models/v02/MODEL_MANIFEST.json` is the machine-readable source of file sizes, hashes, exact class maps, revisions and selected release files. The application source remains AGPL-3.0; third-party weights retain their own notices.

### luminous0219/fire-and-smoke-yolov8n

- Architecture: YOLOv8n; checkpoint-reported training Ultralytics 8.2.83.
- Revision: `c30923f568d915a53fcf85989be9fe5d4e030518`.
- Local file: `models/v02/fire_smoke.pt` (6,262,051 bytes).
- SHA256: `ac0a10257b2bc1f20c9d957f8adeeb61dd6140322fc19d0b4a116cb491776d16`.
- Source: [pinned publisher repository](https://github.com/luminous0219/fire-and-smoke-detection-yolov8/tree/c30923f568d915a53fcf85989be9fe5d4e030518), [checkpoint bytes](https://raw.githubusercontent.com/luminous0219/fire-and-smoke-detection-yolov8/c30923f568d915a53fcf85989be9fe5d4e030518/weights/best.pt).
- License: AGPL-3.0; [pinned license](https://raw.githubusercontent.com/luminous0219/fire-and-smoke-detection-yolov8/c30923f568d915a53fcf85989be9fe5d4e030518/LICENSE); included as `fire_smoke-LICENSE.txt`.
- Exact checkpoint classes: 0: fire, 1: smoke.
- Enabled normalized categories: fire, smoke.

### GingerBrains/YOLOv8s-weapons

- Architecture: YOLOv8s; checkpoint-reported training Ultralytics 8.0.20.
- Revision: `ab6f53c8d18d77d799fa70a46adea646d7bb4499`.
- Local file: `models/v02/weapon_ginger.pt` (22,531,960 bytes).
- SHA256: `a010e4a9a18f9b1ccaffe063334f088d5b64083e4ccd7b9ef2dbc7b183fc2d80`.
- Source: [pinned publisher repository](https://github.com/GingerBrains/object-detection/tree/ab6f53c8d18d77d799fa70a46adea646d7bb4499), [checkpoint bytes](https://raw.githubusercontent.com/GingerBrains/object-detection/ab6f53c8d18d77d799fa70a46adea646d7bb4499/best.pt).
- License: GPL-3.0 repository checkpoint; Ultralytics AGPL-3.0 integration; [pinned license](https://raw.githubusercontent.com/GingerBrains/object-detection/ab6f53c8d18d77d799fa70a46adea646d7bb4499/LICENSE); included as `weapon_ginger-LICENSE.txt`.
- Exact checkpoint classes: 0: Grenade, 1: Gun, 2: Knife, 3: Pistol, 4: handgun, 5: rifle.
- Enabled normalized categories: weapon_firearm, weapon_knife, weapon_handgun, weapon_longgun.

The weapon adapter maps Pistol/handgun to possible handgun, rifle to possible long firearm, Knife to possible knife and Gun to possible generic firearm. A generic Gun output is never renamed handgun or rifle. Grenade is excluded. Knife/long-firearm support has selected positive examples but no representative independent validation; reliability remains experimental. Fire/smoke outputs describe visible appearance, not certified smoke sensing or chemical composition.

## Loading and runtime

Specialized assets must match their pinned SHA256 and exact reviewed class maps. Restricted `torch.load(weights_only=True)` uses a fixed allowlist of installed PyTorch/Ultralytics classes and narrowly reviewed legacy compatibility shims. Unknown serialization classes are rejected. No unrestricted publisher pickle or dill dependency is used. Hash pinning is not an independent publisher signature or universal malicious-model guarantee.

The executed environment uses Python 3.12.15, Ultralytics 8.4.183, PyTorch 2.14.1, torchvision 0.29.1 and OpenCV 4.14.0.94. The actual dependency set is pinned in requirements-lock.txt. CPU and MPS inference ran; MPS operation errors have a CPU fallback. ONNX Runtime and Core ML tooling are not installed or represented as verified execution paths. GHS detection is unavailable in this build.

Inference does not download models or install dependencies. `tools/download_v02_models.py --verify-only` checks local selected models/license bytes offline. Explicit installation has bounded retries and certificate verification. Both actual fresh HTTPS checkpoint downloads passed with the pinned hashes in `docs/evidence/v02-2026-11-01/model-fresh-install.json`.

## Measured detection quality

The development screening contains14 natural photos and 3 derived scenes, one annotator and approximate source-pixel boxes. No training/test disjointness is established. Low-light and occlusion examples are artificial perturbations of the same handgun photo; they are not independent photographs. A derived screen-flame example is explicitly synthetic. Negatives include a drill, hairdryer, bright lighting, lamp, orange reflections, steam, fog and dust. Full provenance/attribution is in FIXTURES_V02.md.

The table below is at confidence 0.35 and input 640. Scene presence asks whether a category is present; strict object scoring requires same-category IoU≥0.5 with an annotation. Fire/smoke aggregate region annotations can disagree with predicted fragments, so object metrics are especially sensitive to grouping. Counts are small and must not be generalized.

| Category | Scene TP / FP / FN | Scene precision / recall | Object TP / FP / FN | Object precision / recall |
|---|---:|---:|---:|---:|
| weapon_handgun | 2 / 1 / 1 | 66.7% / 66.7% | 2 / 1 / 1 | 66.7% / 66.7% |
| weapon_longgun | 1 / 0 / 0 | 100.0% / 100.0% | 1 / 0 / 0 | 100.0% / 100.0% |
| weapon_knife | 1 / 2 / 0 | 33.3% / 100.0% | 2 / 2 / 0 | 50.0% / 100.0% |
| weapon_firearm | 0 / 2 / 0 | 0.0% / undefined | 0 / 2 / 0 | 0.0% / undefined |
| fire | 2 / 2 / 0 | 50.0% / 100.0% | 1 / 6 / 1 | 14.3% / 50.0% |
| smoke | 1 / 2 / 1 | 33.3% / 50.0% | 0 / 4 / 2 | 0.0% / 0.0% |

At confidence 0.60 the selected fire/smoke positives were missed in this still-image screening. Raising a threshold does not establish safety. Retained failures include a drill predicted as handgun/fire/smoke, a campfire predicted as knife, an orange reflection predicted as generic firearm and background blur predicted as smoke. Persistent false positives can pass temporal rules. The occluded handgun was predicted as generic firearm instead of handgun. See model-evaluation.json and the320/480 comparisons for every output, miss and both threshold results.

## Measured inference cost

Both specialized models plus ByteTrack were measured on one real 586 × 400 handgun photo, 12 warm calls per configuration, on the available 16 GB Apple Silicon Mac. These timings exclude ordinary YOLO11n, video decoding, pacing, UI and alert processing; throughput is not end-to-end camera FPS. Cold loading/shape warmup and concurrent engineering work are documented separately in the JSON.

| Device | Input | Warm mean | P95 | Inference-only throughput | Parent RSS |
|---|---:|---:|---:|---:|---:|
| cpu | 320 | 21.50 ms | 22.13 ms | 46.52 calls/s | 497.8 MB |
| cpu | 480 | 37.73 ms | 38.08 ms | 26.51 calls/s | 522.7 MB |
| cpu | 640 | 58.25 ms | 58.77 ms | 17.17 calls/s | 560.8 MB |
| mps | 320 | 24.95 ms | 29.28 ms | 40.08 calls/s | 753.7 MB |
| mps | 480 | 26.74 ms | 32.25 ms | 37.40 calls/s | 806.4 MB |
| mps | 640 | 30.68 ms | 41.68 ms | 32.60 calls/s | 838.6 MB |

At 320 / 480 the sole rifle scene was missed; at 640 it was detected. Fire and smoke outcomes varied across resolutions rather than improving monotonically. Lower resolution can reduce cost but this tiny selected set cannot establish an optimal accuracy/latency operating point. GPU utilization is unavailable; the benchmark records actual MPS allocation counters where supported. Parent RSS excludes capture-child and other unified-memory allocations.

## Natural-motion observations and scope

`natural-motion-model-events.json` evaluates three genuine moving clips at 0.2 s sampling and 0.35 confidence. The fireplace clip produced a real fire alert using 3 consecutive observations and 1 s persistence. The range clip produced handgun observations, but the 1 s rule did not confirm a weapon alert; persistent false smoke and later fire predictions were retained. The industrial smoke clip had 72 analyzed samples and no detections, so moving-smoke success is not claimed. Any later native integration tests or changed thresholds are listed separately in VERIFICATION_REPORT.md.

Zcket/gun_dtct was rejected for an unnamed ambiguous class. Apex-05 weights were evaluated but not selected/distributed because weight-specific licensing was unclear. A smaller MIT handgun/knife candidate lacked rifle support. These rejected candidates do not silently augment the selected detector catalog.
