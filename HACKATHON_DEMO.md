# November 4, 2026 demonstration

## Before presenting

Open this existing project folder, run `install.command` if necessary, then run `test.command`. Read `VERIFICATION_REPORT.md` for the current measured results and remaining gaps. Keep the provided model/fixture license notes with the project.

Use **demo.command** for a prepared local fallback. It preselects the silent public-domain `weapon_range_motion.mp4` and applies a weapon-only profile: confidence0.35, at least3 consecutive analyzed samples, persistence0.3s, maximum gap2s and cooldown30s. Those weaker clip-specific thresholds demonstrated an alert around the brief visible handgun sequence; they increase false-alarm risk and are not a validated deployment setting. Actual model inference remains required on every analyzed sample. It does not start a camera, save incidents/evidence, enable sound or contact anyone automatically. Normal `launch.command` uses saved/default preferences instead.

## Demonstrate the complete flow

1. Open **demo.command**. Explain that this is an uncertain visual-detection prototype with human review.
2. Confirm the selected local clip. Optional: enable Save incident metadata locally, and separately Save incident evidence snapshots, only for this public test footage.
3. Press **Start monitoring**. The handgun becomes visible several seconds into the10-second clip. Show the real possible-handgun box, score, available tracking ID, timestamp, actual FPS and device. No boxes are embedded into the clip.
4. Wait for temporal confirmation and the **POSSIBLE** warning. Explain that a model score does not establish threat or criminal intent.
5. Open **Operator center → Incident center**. Select the alert, add a note and **Acknowledge**, then **Dismiss** this known demonstration item. Show saved history/audit if recording was enabled. Verify/Close follow the same enforced state machine.
6. Return to live view and Stop. In **AI settings**, enable the fire/smoke model (optionally disable weapons for this source). Use persistence0.6s or1s for the flame demonstration. Import/drop `data/v02-demo/fire_repeated_still.mp4`, or `smoke_repeated_still.mp4`. All sources share the same inference/event pipeline. Demonstrate fire/smoke boxes, confirmation and review. Select0.35 confidence in AI settings when using the normal launcher; the0.60 default can miss these specific examples.
7. Show **Diagnostics**: actual model IDs/device/status, inference timings, frame/stream health, dropped samples and process memory. Measurements vary by hardware, cold load and active models.
8. If desired, enable Optional alert sound, adjust volume in settings and use Test enabled sound. Disable it again. Desktop notifications are optional and depend on OS support.
9. Stop monitoring and close the app. Camera/capture resources and worker threads must release.

The default range clip contains genuine natural movement. The separate repeated-still clips contain real licensed photos and demonstrate actual inference → alert → review. They do **not** prove accuracy on natural movement, long occlusions, small/distant weapons, realistic emergencies or every camera. Fixture scope and redistribution permissions are identified in `docs/FIXTURES_V02.md`; the licensed moving-fire stock clip used locally is excluded from the portable ZIP. Keep this distinction clear to the audience.

## Camera and CCTV portion

Choose Mac or iPhone explicitly and press Start; enable hazard analysis. Never stage a weapon or fire for this demonstration. Ordinary objects show that live inference is running; use safe recorded footage for hazard positives. Stop before switching devices. Camera permissions/Continuity availability should be checked on the presentation Mac beforehand.

For an authorized CCTV, use Manage named cameras / ONVIF setup or enter its supported RTSP URL. Use only legitimate credentials; save in Keychain only if desired. Press Start explicitly. If no physical CCTV is available, describe the executed localhost H.264 RTSP integration accurately as a local stream test. A Wi-Fi connection alone does not guarantee camera compatibility.

The developer integration tool `tools/verify_v02_desktop.py --rtsp --video data/v02-demo/fire_repeated_still.mp4 --category fire --output <new project-relative report path>` exercises an actual local RTSP publisher plus the native app. It requires the optional local verification tools under `work/v02-network-tools`, which are not application dependencies or included in the portable source distribution.

## V0.2.1 simultaneous-camera demonstration

Open **Multi-camera monitor**. Use camera management to save only authorized sources with distinct names, optionally use **Nearby CCTV → Refresh nearby CCTV list** on the correct interface, then obtain a compatible stream with legitimate credentials. Check the intended saved cameras and choose **Use checked cameras**. Capture still waits for **Start checked cameras** in the wall. Models and the category filter can be selected there; change the ordinary model while stopped.

Enable hazard models deliberately and keep incident/evidence/sound off unless separately desired. For safe public fixture demonstrations, use alert confidence0.35, display score0.25, at least3 consecutive samples, persistence0.3–0.6s and maximum gap2s; these are disclosed demonstration settings, not validated deployment thresholds. Show both per-camera AI-sampled video images, timestamped possible boxes, actual processing statistics, amber review warnings and the shared Incident center. Stop one feed while the other continues, then Stop all. Recording and review rules remain the same for every source.

The native automated wall verification used two actual localhost H.264 RTSP feeds carrying licensed repeated-still weapon/fire videos and real models. It is a protocol/UI integration test, not two physical CCTV acceptance or natural-motion accuracy. Do not substitute its results for unseen live-camera performance. The existing public moving weapon clip remains the independent single-source motion fallback.

A spoon, scissors, utility knife or blade can still be missed or misclassified. Use the all-objects filter and compare ordinary model choices against the documented selected examples. Show the real error/uncertain output if it fails; do not promise reliable sharp-object or fire detection. Temporal settings cannot recover predictions the model never produced.

## Recovery

If a camera/stream fails, Stop and use the bundled local video fallback. If a model is unavailable, show the real error and rerun the pinned installer; do not substitute simulated detections. If there are misses/false positives, show the retained evaluation and explain limitations. Never present silence as proof that a scene is safe.
