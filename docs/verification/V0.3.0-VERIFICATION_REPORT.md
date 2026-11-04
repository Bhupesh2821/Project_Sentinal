# SENTINAL V0.3.0 — verification and delivery

Report date: November 4, 2026 (Asia/Kolkata). **Status: integrated connected hackathon prototype; the hosted vertical slice has passed; distribution readbacks are recorded in the companion delivery manifest. Detector reliability remains experimental.**

Canonical root: `/Users/prabhuram04yahoo.com/Documents/Bhupesh/Projects/ProjectSentinal`. The pre-V0.3 source checkpoint is `history/implementation-v03-2026-11-03/`; the V0.2.1 reports and archive are preserved. No unrelated project was modified.

## Implemented

- The original Python Vision Core, trained models, exact Mac/iPhone selection, dynamic video import, ONVIF/RTSP sources and bounded camera wall are preserved. No replacement camera framework or mock detections were introduced.
- Explicit desktop outbound metadata connection and a headless monitor reuse actual inference and temporal incidents. HMAC-signed HTTPS delivery, event IDs, bounded persistent retries, replay checks, destination-bound outboxes and measured heartbeats connect to either the local service or the separately paired Base44 gateway. Camera capture and delivery require independent explicit action.
- Responsive public website and private overview/live/models/incidents/cameras/administration dashboard; persisted incidents, viewer/operator/admin permissions, review notes, optimistic versions, audit and retention. Local cookie/CSRF authentication is separate from native Base44 authentication. There is no default human password.
- Private local SQLite authority; a designated Base44 project uses a bounded single-organization state entity with direct row access denied and checked functions as the hosted authority. Local and cloud stores are not bidirectionally synchronized. Hosted incident cap200, audit1000, paired devices32; these are prototype bounds, not a fleet platform.
- Optional loopback-only authenticated RAM preview, off by default and expiring after3s. Hosted video delivery is unavailable. No RTSP URLs, passwords, private footage, evidence paths or facial identities enter incident delivery. Public PWA assets are cached; private data is not.
- Account changes invalidate delayed private responses and clear unsaved drafts. The desktop preserves hosted pairing transport settings and no longer reports active inference after stopping. Exporters exclude private stores, credentials, installed dependencies and build caches.

## Executed validation

The final complete pytest run passed **583 tests, zero failures/skips,64.47seconds, exit0**, recorded in `docs/evidence/v03-2026-11-03/pytest-final.txt`. The earlier pre-final-guard run passed550tests in64.90s; it is preserved separately and is not substituted for the final result.

| Check | Executed result / scope |
| --- | --- |
| Real moving-weapon pipeline |17checks passed: genuine prerecorded movement → actual trained model → temporal incident → signed HTTP on explicit loopback → private API → two cookie sessions → acknowledge/dismiss/audit → database reopen/resource release. `edge-real-inference.json`. |
| Fire and smoke integration |18checks passed each over actual certificate-verified HTTPS, including untrusted-certificate rejection. Real photographs repeated as video; no natural-motion accuracy claim. `edge-fire-https.json`, `edge-smoke-https.json`. |
| Actual Chrome local UI |26checks passed: desktop1440px/mobile390px layouts, real newly received inference alert, actual timestamped annotated preview, two-session review consistency, viewer403, retention persistence, private-cache exclusion, logout and account-switch races. No runtime JS errors. `web-browser.json`. |
| Native macOS V0.3 entry |8checks passed: actual visible application, version, explicit Start, recording/audio/evidence off, clean exit. `native-launcher.json`. |
| Edge focused regressions |41passed4.81s, including malformed credentials, endpoint preservation, signing, retries, queue binding, explicit selection and preview controls. Final full suite includes these tests. |
| Release/source export |48focused tests passed3.66s before final packaging: private-data exclusions, required source paths, model/fixture hashes and Git source snapshot constraints. |
| Prior physical camera and RTSP acceptance |V0.2.1 recorded14Mac checks and37native two-loopback-RTSP wall checks. Not rerun as new V0.3 hardware acceptance; see preserved V0.2.1 report. iPhone was not enumerated then; physical CCTV was unavailable. |

Local browser evidence uses isolated QA accounts and licensed public footage, never private camera pixels. Chrome mobile emulation is not a physical Android/iOS/Windows test. Fire/smoke HTTPS checks use a process-local test CA and do not alter system trust. Component fakes test logic and are not offered as model or hardware proof.

Development failures are preserved: the first mobile browser harness waited for a deliberately hidden connection label, then was corrected. A later resumed browser attempt found the prior QA service stopped; it failed with connection refused, and passed after the isolated service was restarted. Earlier failures remain in the evidence directory and are not relabelled as passes.

## Models and measured behavior

Actual locally executed models remain [GingerBrains YOLOv8s weapons](https://github.com/GingerBrains/object-detection/tree/ab6f53c8d18d77d799fa70a46adea646d7bb4499), pinned GPL-3.0 provenance, and [luminous0219 YOLOv8n fire/smoke](https://github.com/luminous0219/fire-and-smoke-detection-yolov8/tree/c30923f568d915a53fcf85989be9fe5d4e030518), AGPL-3.0 provenance, plus the ordinary Ultralytics detector. Exact classes, hashes and licenses are in `docs/MODEL_MANIFEST_V02.md` and `models/v02/MODEL_MANIFEST.json`. The searchable catalog does not establish accuracy for all labels.

The actual moving-weapon edge run processed300frames/50hazard samples in11.42s, observed26.28processedFPS, mean inference29.36ms and temporal alert latency400.4ms on MPS. This is one paced recorded-clip integration run, not a guaranteed camera/cloud throughput figure. It excludes any claim about new physical multi-camera performance. Model/shape cold load, sample interval and engineering concurrency affect results. See the report JSON for precise timings and queue counters.

No new independent accuracy benchmark or model training was completed by the web integration. The retained V0.2.1 study contains24selected scenes/1,140actual forward passes and substantial false positives/misses; approximate single-annotator labels and no proven train/test independence prevent field generalization. At640/0.25 scene fire scoring was2TP/3FP/0FN, smoke1TP/3FP/1FN; object-IoU scores were worse. Default0.60alert score missed the selected fire/smoke positives. A toy gun triggered the weapon model. Knife/blade/spoon/scissors support remains inconsistent. See `docs/DETECTION_RELIABILITY_V021.md`. Temporal rules cannot recover absent predictions or rule out persistent lookalikes.

## Remaining limits

- Not certified fire/security equipment and not production/field accepted. No perfect tracking, reliable loose-blade detector, toy-versus-real distinction, criminal-intent inference or consequential automated response.
- No hosted CCTV video gateway, mobile push, external recipient, unattended-bag rules, GHS detector, facial identification or compiled Windows/mobile application.
- Physical iPhone/CCTV and Windows/Android/iOS acceptance remain outstanding. ONNX/CoreML execution is unimplemented; actual CPU/MPS evidence is retained from prior model verification.
- The local backend is a bounded prototype, with owner-only plaintext stores and hashed credentials; audit is not tamper-proof. Hosted Base44 data is limited to one organization and bounded history.
- Existing Drive link sharing is preserved at the user's explicit request. Only sanitized distributable artifacts may be uploaded; runtime secrets and private footage must remain excluded.

## Launch and demonstration

Double-click `launch.command` for the desktop, `demo.command` for the selected genuine moving-weapon clip, or `web.command` for the local website/dashboard. First local web launch creates your chosen administrator credentials. The desktop connection dialog loads the intended local or Base44 pairing file; enable delivery and Start separately. Read `HACKATHON_DEMO.md`, `docs/CONNECTED_V03.md`, `docs/EDGE_V03.md` and `docs/API_V03.md`.

## Hosted Base44 vertical slice — executed

Public website: [SENTINAL](https://sentinal-command-center-df4fc282.base44.app). Native-authenticated private dashboard: [Command center](https://sentinal-command-center-df4fc282.base44.app/app.html). Actual app ID6aea0ba86746c1a3df4fc282. Both functions and the freshly built Vite8.3.5 / SDK0.8.40 site were deployed through the official project-local CLI; authenticated owner identity was verified. No new paid plan, public camera gateway or native mobile build is claimed.

- **24 actual hosted Chrome checks passed** at desktop and390px mobile widths: public landing, anonymous sign-in/hidden workspace, same authorized native app identity in two isolated contexts, actual real-model incidents, pinned score/version, acknowledge/dismiss with persistence and cross-context review, native membership/device controls, reload/logout and no uncaught page errors. These contexts use an actual app-scoped credential obtained through the official CLI exchange; they do not establish a fresh Google login or physical mobile acceptance. `base44-hosted-browser.json`.
- **9 actual authority checks passed**: native owner identity, ordinary direct entity access denied, anonymous command401, correct empty initial state, and two concurrent provider compare-and-set writes with exactly one winner. Initial authority was empty; no fabricated operational records were created. `base44-authority.json`.
- **3 actual replay/idempotency checks passed** using an already delivered genuine alert: same event/fresh nonce acknowledged once, reused nonce rejected, changed body with same event ID rejected. `base44-replay.json`.
- **21 Node protocol/role/bounds/CAS tests passed**, zero failures/skips. These pure/component checks are separate from real hosted acceptance. `base44-node-tests.txt`.
- The actual moving-weapon edge run processed722frames/121hazard samples over25.5s, created2candidates/2possible alerts and delivered14metadata envelopes, with0pending/failed. Measured mean inference27.12ms and observed28.31processingFPS on MPS; these are edge processing measurements, not cloud-screen FPS or a measured cloud end-to-end latency. `base44-edge-weapon.json`. A later short actual inference run supplied a fresh incident for the final browser review test. No pixels or evidence were uploaded.

Two initial hosted browser harnesses failed: one status wait matched a fresh audit entry while the mobile record was stale; the backend correctly rejected the stale review version. The second checked camera text before navigation finished. Both failed JSON reports are preserved; explicit status/action/navigation waits passed without changing production review behavior. Public screenshots were visually inspected. **4 read-only post-review checks also passed**, confirming persisted actor/timestamps, version3 and actual rendered acknowledgment/dismissal audit entries (`base44-post-review.json`).

The final release export regressions passed48tests in4.53s after private/provider-link exclusion changes. Git publication uses a source-only feature commit parented to the verified remote main, preserving the existing local working HEAD/index and oversized historical assets. Source publication, PR and Drive checksum/readback identifiers are recorded in the companion `delivery-manifest.json`, distributed alongside the archive. Existing Drive sharing is preserved. **The tested vertical slice is delivered as a prototype; remaining field/device/video/accuracy requirements above are not declared complete.**
