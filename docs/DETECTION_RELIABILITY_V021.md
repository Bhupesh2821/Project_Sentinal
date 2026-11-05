# V0.2.1 detection reliability investigation

The reported live-camera misses were investigated using real local model predictions. A software defect was reproduced and fixed, but this does not establish that spoons, knives, scissors, toys, loose blades or fires are now reliably detected in the user's live scene. That scene was not supplied as a labelled recording. Loose blades remain experimental; no dedicated independently validated blade detector has been added.

## Reproduced software loss and implemented fix

After an empty background frame, Ultralytics' tracked-results path returned no rows for newly appearing objects even though its predictor produced two knife boxes, three fire boxes and two smoke boxes. ByteTrack confirmation was being used as a prerequisite for visibility. The full before/fresh-prediction evidence is in [raw-vs-legacy-tracking.json](evidence/v021-2026-11-02/raw-vs-legacy-tracking.json).

Both ordinary and specialized detectors now call the supported prediction interface, keep current raw source-pixel boxes and confidence, and attach optional ByteTrack IDs using the result's original detection index. New objects and low-score boxes remain visible without an ID. Brief tracking loss or a tracker error no longer erases an available prediction. Source sessions have bounded independent association state. This fixes a display/pipeline omission, not model misclassification.

The dashboard also separates the hazard box display threshold (default0.25) from the temporal incident confidence (default0.60). A fire score0.45 can therefore be shown while awaiting a stronger, persistent incident candidate. Per-category display thresholds are configurable. Lowering a display threshold exposes more uncertain boxes; it also exposes more false positives. The ordinary category filter must include all objects to show spoon/knife/scissors. The people-and-bags filter intentionally excludes those classes.

## Real models and supported categories

The original default remains YOLO11n. The existing YOLOv8n/s Open Images options are preserved in their original menu order. An optional fourth model, official [Ultralytics YOLO11s](https://docs.ultralytics.com/models/yolo11/), uses the same80COCOclasses. It does not add firearm or specialized blade classes. It is supplied under AGPL-3.0 with full source, consistent with the existing Ultralytics integration.

The optional weights are the [v8.4.0 GitHub release asset](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11s.pt),19,313,732 bytes, SHA256 `85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5`. Publisher metadata/source/license links are preserved in models/yolo11s.source.json. The explicit installer checks this pinned digest before publication; no monitoring-time download is introduced.

Specialized models remain the pinned [GingerBrains/object-detection YOLOv8s weapons checkpoint](https://github.com/GingerBrains/object-detection/tree/ab6f53c8d18d77d799fa70a46adea646d7bb4499) and [luminous0219 fire/smoke YOLOv8n checkpoint](https://github.com/luminous0219/fire-and-smoke-detection-yolov8/tree/c30923f568d915a53fcf85989be9fe5d4e030518). Exact revisions, classes, licensing and restricted checkpoint loading are documented in [MODEL_MANIFEST_V02.md](MODEL_MANIFEST_V02.md). Handgun, long-gun, generic-firearm and knife labels retain their distinct meanings. A toy gun may produce a possible visual weapon candidate; the software cannot establish real versus toy or criminal intent.

## Evaluation design and actual counts

[Raw combination matrix](evidence/v021-2026-11-02/detection-combination-matrix.json):24 annotated development scenes comprise21 selected natural public photos and3 previously derived scenes. The seven new photos have two spoon instances, three scissors instances, a cleaver, a utility knife with separate loose spare blade, and a known toy gun. [Fixture credits](FIXTURES_V021.md) and a hashed distribution allowlist accompany them. Approximate boxes were drawn by one developer. The scenes were selected during debugging, with no established training/test independence or representative field sampling.

The executed sweep used input320/640/960, five conditions (original, brightness35%, Gaussian blur, central20% occlusion, object scale30%), four ordinary models and both specialized models. It completed780 frame/model groups representing1,140 actual model forward passes in53.999seconds. Five postprocessed thresholds0.15/0.25/0.35/0.50/0.60 yielded3,900 thresholded frame/model combinations and375 aggregate configurations. Thresholding reuses recorded raw predictions; it is not3,900 independent inference runs. Artificial variants and the three existing derived scenes are not additional natural examples. The sweep timing includes orchestration and model/shape changes; it is not live FPS.

### Ordinary objects, original seven photos,640 input,score≥0.25

Values below are true positives / unmatched predictions / missed labelled objects, with same-category one-to-one IoU≥0.5 matching. Only spoon/scissors/knife predictions are scored; other output classes are retained in the raw file but not exhaustively annotated.

| Model | Spoon TP / FP / FN | Scissors TP / FP / FN | Knife TP / FP / FN |
|---|---|---|---|
| yolo11n | 0 / 0 / 2 | 2 / 2 / 1 | 1 / 3 / 1 |
| yolov8n-oiv7 | 1 / 0 / 1 | 0 / 0 / 3 | 1 / 1 / 1 |
| yolov8s-oiv7 | 2 / 0 / 0 | 1 / 1 / 2 | 1 / 3 / 1 |
| yolo11s | 1 / 0 / 1 | 3 / 2 / 0 | 0 / 1 / 2 |

YOLOv8s Open Images matched both spoons at this threshold, while missing two of three scissors. YOLO11s matched all three scissors and one spoon, but mislabelled the silver spoon and cleaver as scissors. Its0.465 knife output in the utility-knife photo overlaps the separate loose spare blade, not the labelled utility knife. It is evidence of one generic knife-shaped response, not reliable loose-blade recognition. These mixed results do not justify automatically replacing the default or claiming universal improvement from a larger model.

The specialized knife model found the cleaver at0.939 but missed the utility knife at0.25. It also called scissors a knife and produced smoke on a scissors photograph. A known toy produced a0.826 possible-handgun output; for genuine-firearm evaluation it remains a negative and contributes a false positive. There is no hardcoded toy detector or exclusion.

### Specialized outputs, original24scenes,640 input,score≥0.25

| Category | Object IoU50 TP / FP / FN | Scene-presence TP / FP / FN |
|---|---|---|
| weapon_handgun | 2 / 4 / 1 | 3 / 3 / 0 |
| weapon_firearm | 0 / 2 / 0 | 0 / 2 / 0 |
| weapon_longgun | 1 / 0 / 0 | 1 / 0 / 0 |
| weapon_knife | 3 / 4 / 1 | 2 / 4 / 1 |
| fire | 1 / 9 / 1 | 2 / 3 / 0 |
| smoke | 0 / 6 / 2 | 1 / 3 / 1 |

Scene presence asks whether any output of the expected class appears anywhere in a scene. It does not validate localization. Object matching uses approximate coarse fire/smoke region boxes; multiple smaller flame/plume boxes may become unmatched and should not be interpreted as a calibrated field precision estimate. Generic firearm outputs are scored separately from handgun/long-gun labels. This exact-class protocol is deliberately disclosed rather than silently merging away errors.

At the existing0.60 incident threshold, fire and smoke each had0 scene true positives,1 scene false positive and2 scene misses on this set. At0.25 display threshold, both fire scenes had visible fire output but three negative scenes also did; smoke appeared in only one of two smoke-labelled scenes and three negative scenes. Increasing input to960 did not resolve these weaknesses: original-scene fire IoU50 became0TP/12FP/2FN and smoke0TP/10FP/2FN. Higher resolution alone is not a reliability fix. Temporal persistence can limit repeated alerts but cannot reliably remove a persistent lookalike or recover an absent prediction.

## Verification and remaining acceptance

Fresh final focused verification:87 detector/tracker/catalog/installer/release tests passed in2.99seconds. This combined count includes the new optional-model integrity, public-fixture privacy and installation-failure regressions; it supersedes earlier overlapping targeted runs. The raw console result is preserved in [detector-regression-final.txt](evidence/v021-2026-11-02/detector-regression-final.txt). Actual release selection validated all360 currently selected files, including the optional model, source/checksum pins and16 reported-item fixture entries (15hashed files plus their manifest). The real matrix uses loaded pretrained models; unit tests of failure handling and UI-facing contracts are separate from accuracy evidence. Read the current root verification report for the final integrated suite and desktop results.

Remaining evidence needed for a reliability claim: consented labelled live-camera recordings of the user's objects, multiple viewpoints/backgrounds/distances, representative moving fire/smoke and lookalikes, unseen camera deployments, independently held-out annotations, and threshold selection separated from final evaluation. No finite combination sweep prevents every false positive or false negative. This remains a human-reviewed prototype, not a certified fire detector or autonomous threat judgement.

Reproduce the saved bounded sweep after installation by running tools/evaluate_detection_matrix_v021.py from the project environment. It requires the reviewed local fixtures and selected weights. Models do not fetch media during monitoring.


## Fresh measured processing cost

The warm benchmark ran sequentially on the available16GB Apple Silicon Mac using PyTorch2.14.1. All rows actually used MPS. Each configuration used one real licensed cleaver photo downsampled proportionally to640×480, one first call plus three additional warmups excluded, then12 measured calls. This is model prediction plus ByteTrack association, excluding camera decoding, display, incident processing, other active models and source pacing. Calls/second below are inference-only throughput, not camera monitoring FPS. Parent RSS excludes capture processes and some GPU/driver allocations; the raw report also records MPS allocation counters.

| Model | Input | Mean ms | P95 ms | Calls/s | Parent RSS MB |
|---|---:|---:|---:|---:|---:|
| yolo11n | 320 | 16.90 | 17.14 | 59.17 | 532.4 |
| yolo11n | 640 | 21.47 | 26.05 | 46.57 | 574.4 |
| yolo11n | 960 | 27.04 | 31.44 | 36.98 | 616.4 |
| yolov8n-oiv7 | 320 | 17.77 | 28.97 | 56.28 | 621.8 |
| yolov8n-oiv7 | 640 | 25.85 | 37.60 | 38.68 | 622.5 |
| yolov8n-oiv7 | 960 | 24.86 | 25.94 | 40.23 | 624.6 |
| yolov8s-oiv7 | 320 | 21.08 | 38.11 | 47.44 | 694.1 |
| yolov8s-oiv7 | 640 | 25.95 | 27.48 | 38.53 | 694.2 |
| yolov8s-oiv7 | 960 | 69.47 | 100.06 | 14.39 | 695.8 |
| yolo11s | 320 | 10.69 | 11.80 | 93.59 | 701.7 |
| yolo11s | 640 | 23.96 | 26.14 | 41.73 | 701.8 |
| yolo11s | 960 | 49.59 | 63.80 | 20.17 | 706.0 |
| Both specialized models | 320 | 25.42 | 31.25 | 39.34 | 726.4 |
| Both specialized models | 640 | 31.60 | 36.47 | 31.65 | 726.5 |
| Both specialized models | 960 | 61.84 | 92.97 | 16.17 | 755.6 |

Small timing differences, such as the lightweight Open Images960 result being slightly faster than640, are observations of this short run with uncontrolled host load; they are not guarantees of a monotonic performance advantage. Model order, shape warmup, fixed overhead and noise matter. The larger Open Images and YOLO11s variants and both specialized models were substantially slower at960. The accuracy sweep did not show960 reliably fixing misses.640 remains a reasonable initial setting, with an operator-adjustable resolution and explicit model choice. Multiple cameras share inference and divide the available throughput.

Reproduce with tools/benchmark_detection_v021.py --device mps --samples 12. [Raw warm benchmark](evidence/v021-2026-11-02/detection-warm-benchmark-mps.json). The previous V0.2 CPU/MPS comparison remains historical evidence for the earlier pipeline; no fresh CPU benchmark is claimed for this update.
