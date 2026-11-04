# Camera and field acceptance

Use this procedure for requirements marked BLOCKED or NOT VERIFIED in VERIFICATION_REPORT.md. Do not infer success from unit tests.

1. Launch `launch.command`. Confirm metadata recording is unchecked and the camera indicator stays off before Start.
2. Select the built-in camera and press Start. If denied, confirm a readable error, enable access for the named host in System Settings → Privacy & Security → Camera, then relaunch and start again.
3. In good lighting, walk through view with a backpack, then a handbag, then a suitcase. Compare category/confidence against the actual item. Test both object filters and all overlay toggles. Record misses and false positives; do not lower confidence solely to manufacture a pass.
4. Have two people and two bags move independently, cross and briefly occlude each other. Record track losses and ID swaps. Numerical ID persistence alone does not prove correct identity.
5. Stop and confirm the camera indicator turns off. Start/stop five times. Switch to another camera. Disconnect an external camera during monitoring and confirm readable error recovery and resource release.
6. Load real moving-bag footage. Confirm bags are detected and tracked in that footage. Run to EOF, replay and switch to a second independent source. Saved metadata must use new session UUIDs after source changes/replay.
7. Enable metadata for five seconds, then stop. Inspect sampled rows locally. Disable recording and confirm no further rows. With the app closed, remove the acceptance database if not needed.
8. Compare 320, 480 and 640 inference sizes for 30 seconds each using the same source. Record FPS, average vision latency, small-object misses and UI delays. Use `--device cpu` or `--device mps` when checking backends; displayed device must reflect actual fallback.
9. Close during monitoring. Confirm process exit and camera release. A forced OS kill cannot execute Python cleanup; macOS releases capture handles, and SQLite recovers committed transactions next open.

Acceptance log: date/hardware, camera model, permission host, weights SHA256, size/backend, footage provenance, observed detections, misses/false positives, ID changes, FPS/latency, stop/close behavior, unresolved defects. Names and sensitive personal traits are unnecessary.
