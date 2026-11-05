# SENTINAL V0.2.1 — verification and delivery

Report date: November 3, 2026. Demonstration target: November 4, 2026.

**Status: integrated local desktop prototype; detection reliability and field acceptance remain partial.** The software defects that hid available predictions and made hazard boxes flash were reproduced and corrected. A real simultaneous-camera dashboard now reaches local alerts and review. This does not mean the reported live spoon/knife/scissors/toy/blade/fire misses are all solved. The selected models still make substantial errors. There is no dependable general sharp-object or emergency recognition claim.

All project-owned files remain under `/Users/prabhuram04yahoo.com/Documents/Bhupesh/Projects/Project Sentinal`. No duplicate application was recreated at the old path. The previous verified V0.2.0 archive is preserved, and the pre-update checkpoint is in `history/implementation-v021-2026-11-02/`. Earlier verification is retained in [V0.2.0 report](docs/verification/V0.2.0-VERIFICATION_REPORT.md).

## Delivered behavior

- Ordinary and specialized predictions remain visible before ByteTrack assigns an ID. IDs attach to current raw source-pixel predictions instead of replacing/filtering them. Source/session/model tracker state is isolated and bounded; failure retains boxes without IDs.
- Hazard box display confidence defaults to0.25, separately from the0.60 temporal alert threshold. Optional category display scores and an explicit all-objects/hazard-model shortcut are integrated. A lower display threshold does not silently weaken incident rules.
- The latest complete analyzed frame is retained between hazard samples and visibly timestamped. Boxes never transfer onto newer unanalyzed pixels. A new empty analyzed sample removes old boxes; disabled/unavailable models and a new session release the retained view. This trades picture cadence for accurate overlay provenance. The displayed processing FPS is measured from processed packets, not screen refresh rate or hazard sample frequency.
- Nearby CCTV is a refreshable ONVIF service list for a selected reachable IPv4 interface. Advertisement, authentication and video remain distinct states. Manual legitimate ONVIF/RTSP/HTTP sources remain available; no subnet/port scan or automatic capture is used.
- Saved cameras can be checked together and explicitly started in a camera wall, up to8 sources. It uses existing capture adapters and one shared ordinary/specialized model set with serial fair inference. Capture and tracking sessions remain independent. Each tile has measured health/performance, possible observations, Stop and a visible review warning. Incident review/history is shared.
- The incident mailbox retains a latest sample per camera, capped at8; a fast source cannot erase every slower-source sample. Model selection is locked while either monitoring mode owns capture. Reopening the same source waits for resource release; failed cleanup prevents competing reconnect/retry.
- Optional official YOLO11s is the fourth object profile. The original three choices/default remain. It has mixed measured outcomes, not a universal accuracy improvement.
- Existing dynamic import/drop/pause/seek/replay, exact Mac/iPhone identity selection, local recording policy, CPU fallback and explicit controls remain. No microphone, face identification, intent inference, emergency-service call or remote recipient was added. Recording, evidence, sound and desktop notifications start off.

## Executed tests

The final integrated automated run completed **476 passed, zero failed/skipped,20.03seconds, exit0**. This includes the preserved tests, actual available recorded-video inference and new detector/association, settings, camera/network, scheduling, lifecycle, incident intake, UI and packaging regressions. Component fakes are identified and do not establish physical hardware or model accuracy.

| Check | Actual outcome | Evidence |
| --- | --- | --- |
| Full automated suite |476passed,0failed/skipped,20.03s | [pytest-final.txt](docs/evidence/v021-2026-11-03/pytest-final.txt) |
| Actual application entry |8native launch/version/privacy/exit checks passed | [launcher.json](docs/evidence/v021-2026-11-03/launcher.json) |
| Actual moving-weapon demo |12checks passed; real model box→possible alert→Stop/clean exit; recording stayed off | [demo-entry.json](docs/evidence/v021-2026-11-03/demo-entry.json) |
| Native two-camera wall |37checks passed, no errors: actual two localhostH.264RTSP feeds→real weapon/fire outputs→both overlays→candidate/alerts→acknowledge/dismiss→SQLite/audit→independent Stop→close/reopen | [camera-wall-native-final.json](docs/evidence/v021-2026-11-03/camera-wall-native-final.json), [screenshot](docs/evidence/v021-2026-11-03/camera-wall-native-final.png) |
| Wall controls / presentation |21UI component tests passed after final model-control ownership fix; included again in final476 | [UI tests](docs/evidence/v021-2026-11-03/camera-wall-ui-tests.txt) |
| Two-stream reconnect core |14real integration checks passed: source interruption/recovery, other feed preserved, same loaded models, separate sessions/events and cleanup | [multi-camera-rtsp-2026-11-03-final.json](docs/evidence/v021-2026-11-02/multi-camera-rtsp-2026-11-03-final.json) |
| Multi-camera failure/scheduling matrix |28component tests passed, including1/2/4/8sources, fast restart, aliases, failed cleanup, EOF, independent Stop and all/focus/safety filters; included in final suite | tests/test_multi_camera_v021.py |
| Actual built-in Mac camera |14checks passed, two10-second live cycles;452observed processed packets/57specialized samples; exact identity, both models active, resources released, storage unchanged | [native-cameras.json](docs/evidence/v021-2026-11-03/native-cameras.json) |
| Phone camera |Blocked: not enumerated at explicit selection step; no substitute opened | Same native camera report |
| Nearby CCTV interface |53focused tests and12native controlled-advertiser checks passed; actual UDP, deduplication and explicit batch selection, no capture | [network tests](docs/evidence/v021-2026-11-02/network-tests.txt), [native list](docs/evidence/v021-2026-11-02/nearby-native-loopback.json) |
| Current LAN discovery |3.00s actual bounded discovery received1advertised service; names/endpoints hashed; no sign-in/video | [nearby-real-lan.json](docs/evidence/v021-2026-11-02/nearby-real-lan.json) |
| Local/offline models |Actual selected weapon/fire/smoke inference on MPS and CPU with Python socket connection/send paths blocked; zero connection attempts | [MPS](docs/evidence/v021-2026-11-03/offline-mps.json), [CPU](docs/evidence/v021-2026-11-03/offline-cpu.json) |
| Real model combinations |780frame/model groups/1,140actual forward passes,24selected scenes, five artificial conditions,320/640/960; numerical threshold postprocessing separately counted | [reliability investigation](docs/DETECTION_RELIABILITY_V021.md) |

The37-check native wall run preceded the final control-only guard against changing the model from an idle wall while the single-source worker is busy; the21UI checks and final476suite include that guard. It did not change camera decoding, inference or alert rendering.

Development failures are retained: the first core RTSP rerun used stdin and failed macOS process spawning before real integration. Running its actual file entry succeeded. The first full-suite run had474passed/1failed because a cleanup test consumed an earlier error instead of waiting for a fresh retry result. Its predicate was corrected to wait for the new error and cleanup; final retries passed. No failed run was relabelled as successful. See the initial RTSP report and `pytest-initial-retry-race.txt`.

The socket guard verifies Python code paths, not an OS-level packet capture. No private camera images, object records, snapshots or audio were saved in physical-camera validation. Native wall screenshots contain only approved public fixtures. The two RTSP feeds use real licensed photographs repeated as video; they are not natural-motion accuracy or physical-CCTV acceptance. The separate moving-weapon demonstration uses genuine recorded movement.

## Actual models and measured quality

| Module | Model / source | Meaning and limitation |
| --- | --- | --- |
| Ordinary objects |Official Ultralytics YOLO11n(default), YOLOv8n/s OpenImages; optional [YOLO11s](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11s.pt) |Spoon/scissors/knife labels where trained; no generic reliable sharp-object detector |
| Possible weapons |[GingerBrains YOLOv8s](https://github.com/GingerBrains/object-detection/tree/ab6f53c8d18d77d799fa70a46adea646d7bb4499) |Pinned handgun/rifle/generic-firearm/knife classes; toy versus real cannot be established |
| Fire / smoke |[luminous0219 YOLOv8n](https://github.com/luminous0219/fire-and-smoke-detection-yolov8/tree/c30923f568d915a53fcf85989be9fe5d4e030518) |Visible flame/smoke predictions, with retained misses and lookalike errors |

Full revisions, SHA256, class maps and license files are in [model manifest](docs/MODEL_MANIFEST_V02.md), [optional model provenance](models/yolo11s.source.json), and [license notes](LICENSE_NOTES.md). The source distribution is AGPL-3.0; weapon repository/checkpoint GPL-3.0 and fire/smoke AGPL-3.0 provenance are retained. Training-data rights/disjointness were not independently audited.

The real development matrix used21selected public photographs plus3existing derived scenes, approximate annotations by one developer, and no proven training/test independence. It is not representative field validation. Five postprocessed score levels create3,900thresholded frame/model combinations; these are not3,900independent inference runs. [Full scores and fixture credits](docs/DETECTION_RELIABILITY_V021.md) retain precision/recall, TP/FP/FN, artificial-condition definitions and errors.

At640/0.25 on the seven new object photos, OpenImages small matched2/2spoons but1/3scissors; YOLO11s matched1/2spoons and3/3scissors while wrongly labelling the cleaver and silver spoon as scissors. Its knife box on the utility-knife photograph overlaps the separate spare blade, not the utility knife. Specialized knife found the cleaver at0.939 but missed the utility knife and falsely labelled scissors as knife. The known toy produced a0.826possible-handgun response; it remains a negative/false positive for genuine-firearm evaluation.

At640/0.25 across the24original scenes, scene-presence fire scoring was2TP/3FP/0FN and smoke1TP/3FP/1FN. Exact-class IoU≥0.5 object matching was fire1TP/9FP/1FN and smoke0TP/6FP/2FN, sensitive to coarse regional annotations and fragmented outputs. At the0.60alert threshold both fire/smoke positives were missed in scene scoring. Higher resolution did not consistently fix this. The prior naturally moving industrial smoke clip was missed and remains unresolved. Persistent reflections/screens/tools can still alert after temporal confirmation. The ordinary model also called the public handgun a suitcase in the native wall; that error remains visible rather than being edited away.

**The user's exact live objects/background were not supplied as labelled footage and were not reproduced.** No independently validated loose-blade detector was added. No tested model/settings remove all false positives or false negatives; improving field reliability requires representative consented labels, training/calibration and independent held-out testing.

## Measured performance

Actual machine/runtime: Apple Silicon M4/16GB, macOS arm64, Python3.12.15, Ultralytics8.4.183, PyTorch2.14.1, PySide6 native Cocoa. MPS used for live tests; actual CPU model inference also passed. Current ONNX/CoreML execution is unimplemented/unverified.

| Observation | Measured result / scope |
| --- | --- |
| Mac live camera, two10s windows |Median processing26.66/26.11FPS; median total per-packet inference17.34/18.94ms, including many base-only packets; hazard samples execute separately. Stop117/120ms. |
| Actual two-stream native wall, short session |Mean worker processing10.30/9.51FPS; mean total inference on observed specialized sample packets60.80/62.15ms; peak parentRSS998.95MB; Stop all97.92ms. Source is10FPS public repeated-still RTSP. |
| Native wall responsiveness |229Qt heartbeat ticks; maximum observed gap398ms during cold workload. Responsive workers do not guarantee zero UI pauses. |
| Moving demo confirmation |400.4ms of source media time from first observation to alert under explicit0.35score/0.3s profile; not emergency-response latency. |
| Warm640MPS, one resized real cleaver photo |YOLO11n21.47ms; OpenImages nano25.85ms; OpenImages small25.95ms; YOLO11s23.96ms; both specialized models31.60ms.12measured calls/config after4warmups; inference+tracking only, excludes source/UI. |

Full320/640/960warm results and resource scope are in the reliability investigation/benchmark JSON. Cold calls were slower and are retained. Processing FPS is not display refresh, hazard-analysis frequency or a sustained hardware guarantee. Four/eight physical feeds, long-duration monitoring, camera encoder latency and complete system/GPU memory/utilization are not measured by these short runs. ParentRSS excludes independent capture processes.

## Outstanding acceptance and launch

Built-in Mac capture, dynamic local-video core, actual selected-model inference, real boxes, tracking association, temporal alerts, native two-stream review/history and bounded cleanup have demonstrated paths. Remaining partial/blocked scope: iPhone availability; physical CCTV authentication/video; simultaneous physical Mac+iPhone+CCTV;4/8physical-feed performance; representative sharp-object/fire/smoke reliability; naturally moving smoke; long field endurance. No signed standalone macOS app, remote notification service or Base44 website was built.

Double-click `launch.command` in this folder, choose the exact source and press Start. Use **Show all objects + enable weapon / fire models** when testing the reported ordinary objects; choose the installed object model and inspect actual results. Use **Nearby CCTV** for advertised services and **Multi-camera monitor** for checked saved cameras, then explicit Start. Open **Operator center** for thresholds/review. For the hackathon use `demo.command` and [HACKATHON_DEMO.md](HACKATHON_DEMO.md); keep the licensed local-video fallback available. Never stage a dangerous weapon/fire to obtain a demo positive.

For outstanding phone acceptance, enable permitted Continuity Camera use on the presentation devices, refresh the exact camera list, deliberately select the phone and Start. Verify fresh video/model diagnostics and Stop/release, then choose Mac explicitly. For physical CCTV, obtain an authorized ONVIF/RTSP endpoint/credentials, select its advertised service or enter the address, authenticate and confirm actual decoded frames; repeat disconnection/recovery and camera-wall coexistence. Do not interpret an advertisement or no error as video acceptance.

All media/metadata stay local by default. User videos are not automatically removed. Optional incident/evidence stores enforce configured retention on use; credentials persist only by explicit OS Keychain choice. See README and existing storage/incident documentation for access/retention limits. A full Base44 managed-cloud migration would conflict with local-only storage unless that policy is explicitly changed: [feasibility assessment](docs/BASE44_FEASIBILITY.md) recommends keeping the local inference/camera service and treating the web/app interface as a future tested integration.

The V0.2.1 source/selected-weight/public-fixture ZIP is generated under `archives/` with checksum/integrity/privacy checks. Its final results are recorded separately in `docs/evidence/v021-2026-11-03/archive-check.json`; the previous V0.2.0 ZIP remains unchanged. Installation/launch documentation, model licensing, raw evaluation, architecture and future BAGWATCH interfaces are included. This source package needs local dependency installation; it is not a signed `.app`.
