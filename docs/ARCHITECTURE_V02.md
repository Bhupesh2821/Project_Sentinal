# V0.2 architecture and extension points

V0.2 extends the preserved V0.1.2 source; the baseline archive and request are in `history/implementation-v02-2026-10-30` and `history/requests`. Existing versioned reports remain in `docs/verification`.

## Data flow

`SourceSpec → VideoSource / LiveVideoSource → VisionPipeline → FramePacket → InferenceWorker → VideoPanel / StatisticsPanel`

The same pipeline handles files, exact-ID Mac/iPhone cameras and supported RTSP/HTTP streams. Native cameras use the existing Qt adapter inside an isolated capture process. Live sources keep only the newest shared frame. Explicit Stop/shutdown releases capture and shared memory. Network loss uses bounded exponential backoff and fresh tracking sessions.

`VisionPipeline.configure_hazards → SpecializedSuite → HazardObservation → IncidentWorker → TemporalEventEngine → Incident → MainWindow / LocalAlertOutput / optional IncidentDatabase / optional EvidenceStore`

The base object detector and specialized models have distinct provenance. Specialized observations are never relabelled as ordinary COCO/OpenImages detections. Each specialized observation includes category, actual score, source-pixel box, optional model-specific tracker ID, model ID/version and detector module. Unsupported classes are excluded. Raw catalog membership never creates an incident.

## Ownership and bounds

The inference QThread owns loaded models and tracking. Its command queue is bounded; the GUI polls a one-packet mailbox rather than accumulating Qt frame signals. Models remain loaded across same-model source changes. Runtime inference never installs dependencies or fetches weights. Confidence/resolution changes configure the existing suite instead of reloading every frame. CPU fallback follows an MPS operation failure.

Specialized models run at the configured source-time sample interval. Unsampled frames do not count as observations. Empty freshly analyzed samples reach the temporal engine and break unconfirmed sequences. Tracking resets on source/session/seek boundaries. Display pixels remain unmodified by overlays.

The incident QThread owns its engine and SQLite connection. Its newest-sample mailbox holds one frame, commands are capped at64, session incidents are capped and temporal source/track state is bounded. A slow incident consumer may drop samples rather than block live inference. This conservative policy can reduce confirmation coverage. Queue sizes are fixed in this prototype, not user-tunable. Diagnostics shows skipped samples.

SQLite uses the existing local-storage stack. A separate incidents schema/database preserves the historical detection store and its semantics; it is not a new service or database engine. Recording/evidence/output activation requires runtime opt-in. Accepted review commands drain during orderly shutdown. Optional write failure is reported and disables recording while still allowing an uncertain visual alert.

## Temporal semantics

Rules validate confidence, consecutive fresh samples, minimum persistence, maximum gap, box overlap, cooldown and severity independently. Track associations include source/session/model/version/category, with tracker identity or overlap matching. Rules may be overridden by stable camera/source ID. Multiple distinct objects may alert separately. Occlusion, false positives and identity changes remain limitations.

The engine emits OBSERVED, CANDIDATE and ALERTED. The operator can acknowledge, verify, dismiss and close according to valid transitions. Automated updates cannot undo review. Model scores never prove danger. `alert_latency_ms` is media-time confirmation delay, not total camera-to-operator wall latency. Verification tools separately report their measured displayed-observation-to-alert interval and transport/model costs.

## Security boundaries

Specialized assets are pinned by revision and SHA256, with exact class-map checks. Restricted `torch.load(weights_only=True)` permits a reviewed installed-framework allowlist; unknown serialized classes fail closed. No arbitrary publisher code or unrestricted dill load is used. This reduces risk; it is not a universal malicious-model security guarantee.

The camera registry stores names/connection health without complete URLs/passwords. Session-only credentials are default; explicit persistence uses macOS Security.framework Keychain. Credentials are not passed in shell arguments. ONVIF setup is bounded and authorized; it does not scan unrelated networks or bypass authentication.

The account owns0700 incident/evidence directories and0600 files. Audit includes local account, decision, note and time. Evidence hashes are checked before preview. There is no separate multiuser authorization service, application-layer evidence encryption or cryptographically immutable audit. External notification adapters remain unavailable. Microphone capture, facial identity, individual profiling and intent inference are absent.

## Diagnostics and backend scope

FPS, decode/read time, base/specialized inference latency, frame age/drop counters, parent process RSS and CPU percent are measured. Native Qt pixel-conversion messages do not describe the PyTorch inference backend. Specialized model health shows its actual CPU/MPS device separately. GPU utilization is unavailable. RSS excludes capture-child and unified-memory allocations outside parent RSS; see benchmark notes.

ONNX Runtime/Core ML are investigated alternatives, not enabled inference paths unless separately converted and validated. The tested runtime is pinned PyTorch/Ultralytics. No unmeasured backend is represented as faster.

## Future BAGWATCH and event modules

A future module can consume immutable `FramePacket` base detections for source-pixel geometry and session-scoped tracks, then emit its own structured observations/events. Keep person-object association and dwell rules in a separate core module; do not add ownership guesses to the detector. Reset on session/seek and keep state bounded. Add validated categories/rules through the event boundary only after model/rule evaluation.

Reuse incident review, local output adapters, optional storage and evidence controls for future events. Extend the schema with a migration and preserve existing records. A headless edge process can use `VisionPipeline`, `TemporalEventEngine` and SQLite independently of MainWindow; Qt worker/UI components are optional adapters. No unattended-bag, violence, gas, chemical-composition or emergency-contact feature is implemented by this extension guide.


## V0.2.1 additions

`RawTrackerBank` attaches optional ByteTrack IDs to original prediction rows; raw boxes are never filtered by track confirmation. `VideoPanel.present_packet` keeps complete sampled frames/predictions together when hazard sampling is slower than ordinary processing. Box display thresholds and incident rule confidence are independent.

`MultiCameraWorker` reuses the existing capture adapters, owns one ordinary detector and specialized suite on its inference thread, and schedules latest frames from up to eight bounded source pumps. Session UUIDs isolate source tracking and incident identities. No model is reloaded per frame. Capture failures/reconnects are per source; a shared fatal model failure remains a diagnostic error. Capture cleanup gates reopening the same ID/resource.

The shared `IncidentWorker` receives one latest packet per source in an ordered mailbox capped at eight. Fast sources cannot overwrite every slower-source sample. The same temporal engine, SQLite/evidence stores, human review and local alert output serve single-source and wall inputs. UI signals carry actual source IDs. The wall holds resolved credentials in memory only for its active selection and clears references on close; camera registry policy is unchanged.

Future BAGWATCH should consume the immutable per-source FramePacket and emit separate rule events into the existing incident service. It must distinguish base-model track IDs from model-specific hazard IDs and namespace all tracks by source/session/model. Detection is not person identity. No unattended-bag association/dwell logic is implemented.
