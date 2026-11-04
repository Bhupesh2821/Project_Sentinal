# V0.3 outbound edge and local monitor

The existing Python Vision Core remains the camera/inference owner. Connecting it is an explicit runtime action. Importing the modules, loading saved device credentials or opening the desktop application does not transmit events or start a camera.

## Desktop integration

Use the desktop's connected-device setup to load the backend origin, registered device ID and secret. Enable outbound metadata deliberately. `DesktopEdgeBridge` attaches to the actual `IncidentWorker.incident_changed` signal; only `ALERTED` observations are published. Local metadata/evidence recording and connected delivery are separate controls. Turning on network delivery authorizes the selected incident metadata and health, without enabling image/evidence recording.

`DesktopEdgeBridge.start(EdgeConfig)` starts the background owner. `stop()` stops further intake and requests asynchronous shutdown; an already in-flight request can finish within its bounded timeout. `close(timeout=5)` waits during orderly application exit. Already accepted metadata is drained to the local spool before stopping and can resume after an explicit re-enable of the same connection. The bridge exposes actual queued/failed/delivered counters and errors.

No camera stream URLs, credentials, frames, face identities, local evidence paths, human review notes or raw exception messages enter the event envelope. Incident metadata includes the camera/session ID, category, actual confidence, source-pixel box, available track ID, timestamps and pinned model provenance. A `POSSIBLE` alert remains uncertain and requires human review.

## Signing and storage

`EdgeConfig` accepts an HTTPS origin, a registered device ID and a secret of at least32 characters. TLS certificate verification is mandatory. An optional local CA file must stay in the project. Plain HTTP requires explicit development opt-in and a literal loopback IP; it cannot target a LAN or public server. Redirects never receive the device headers, and ambient proxy configuration is not inherited.

The default route is `/api/edge/events`. The reviewed Base44 event gateway route `/functions/ingest` is the only other accepted transport path. Both sign the stable logical action `/api/edge/events`; the cloud gateway must verify the same protocol. An arbitrary path cannot be configured. Cloud preview is unavailable.

Shared protocol helpers generate canonical JSON and HMAC-SHA256 authentication over protocol version, method, logical path, device ID, Unix timestamp, fresh nonce and exact body digest. Retries keep the exact event ID/body and use a new nonce. A valid JSON acknowledgment must contain `ok:true` and the same event ID before deletion from the outbox. Invalid/mismatched replies retain the metadata for bounded retry; redirects and ordinary4xx failures become visible failed entries.408/425/429 and5xx failures use bounded retry, including `Retry-After`. No backend response body is retained in diagnostics.

Device credentials default to `config/connected/edge-credentials.json`, mode0600, with an owner-only parent directory. Secrets are owner-local plaintext; application-layer encryption and protection from an already compromised local account are not claimed. Do not commit or share the credentials. The backend stores a derived HMAC key, which is also a signing credential and must remain protected.

The default spool is `recordings/connected/outbox-<connection fingerprint>.sqlite3`. Its fingerprint includes backend origin, transport route, device ID and credential authority. A different endpoint, device or secret uses a different spool. Explicit paths also persist/check the complete binding. Pending metadata is never silently forwarded to a newly configured destination; unbound legacy data requires explicit migration. This prevents reconfiguration from leaking an earlier connection's incidents.

The command queue defaults to128 entries, the persistent spool to500 entries, and maximum retention to7days on active use. Successfully accepted events are removed. Capacity rejection, retry exhaustion and expiry are observable. Different/abandoned connection spools require local deletion or a future retention pass; no continuous secure-erasure service is claimed. Parent-directory permissions and SQLite files are private. No preview images enter SQLite or the persistent outbox.

Connected human review is authoritative at the selected backend. Local desktop incident review remains local; device delivery cannot impersonate a human or overwrite a backend review. There is no uncontrolled bidirectional synchronization of desktop SQLite and the connected store. Two authenticated browser clients can access/review the same backend records subject to their roles and organization.

## Explicit headless monitor

The command below starts actual local recorded-video inference and metadata delivery using an already registered device. Replace paths/settings with the intended authorized source; camera capture is not an implicit default.

```sh
cd "/Users/prabhuram04yahoo.com/Documents/Bhupesh/Projects/ProjectSentinal"
PROJECT_DIR="$PWD"
. "$PROJECT_DIR/runtime-env.sh"
.venv/bin/python -m sentinal.connected.monitor \
  --config config/connected/edge-credentials.json \
  --video data/v02-demo/weapon_range_motion.mp4 \
  --detectors weapons --display-confidence 0.25 \
  --alert-confidence 0.35 --persistence 0.3 --max-gap 2
```

These weaker thresholds are explicit demonstration settings for this brief public clip, with a false-alarm tradeoff. Normal default alert confidence is0.60/persistence1s; current selected-model fire/smoke examples can be missed at that threshold. Neither profile is an independently calibrated deployment setting.

Sources are mutually exclusive:

- `--video <path>` selects an actual local file. Files pace to media time by default; `--unpaced` is an explicit benchmark option. `--loop` restarts a file with a fresh tracking/session boundary while reusing loaded weights.
- `--camera-device-id <exact hexadecimal identity>` uses the existing exact-device camera adapter. Obtain the identity from the existing camera infrastructure. A missing selected device does not open another camera. Stop another owner of that same physical camera before starting a separate headless process.
- `--stream-url-file <owner-only project file>` reads a legitimate RTSP/HTTP URL from a bounded mode0600 file. Do not put camera passwords in command-line arguments. Stream retries are bounded, use the existing capture adapter, and reset temporal state after reconnect.

Use `--camera-id` for an explicit stable logical source identity, especially across credential changes; otherwise a device/source-derived hash is generated. `--name` is the intentionally shared display label. `--max-seconds` bounds a session, and Ctrl+C releases its source and delivery owners. Optional `--report` writes structured local metadata without source URLs or images; detailed alert entries in that report are capped at500. Processing statistics are measured; sampling, pacing, cold load and network drain affect throughput. The diagnostic report is not an accuracy benchmark.

## Optional local browser preview

Preview requires both the monitor's `--preview` flag and the backend's `--allow-local-preview` setting. This implementation accepts only a literal loopback backend origin and the local API route. It does not stream to Base44, a public endpoint or an arbitrary LAN receiver. A separate secured/authorized remote video gateway remains future work.

The background preview owner retains at most one newest frame, encodes an annotated JPEG from its exact actual model input, and sends at most the configured0.2–5FPS(default2). Frames are held only in memory, are timestamped, and expire at the backend after3seconds. Only a currently active camera belonging to that authenticated device can receive a preview; the browser must be authenticated in its organization. The input ndarray is never painted in place. A new frame replaces the mailbox; errors do not switch to fake video or save clips. Network requests use the same verified TLS/HMAC machinery and a separate logical preview path. Local browser preview is not RTSP exposure or general WebRTC/mobile feed support.

## Executed evidence

- `docs/evidence/v03-2026-11-03/edge-tests.txt`:41 focused edge/monitor component tests passed in4.81seconds after malformed-config validation was tightened. Includes real local HTTP and SQLite for signing/retry/redirect/ack behavior, immutable event bytes, queue bounds, destination isolation, owner-only credentials, privacy projection, explicit camera identity, Qt signal opt-in, and local preview restrictions. Synthetic DTOs in these tests do not establish detector accuracy.
- `docs/evidence/v03-2026-11-03/edge-real-inference.json`:17 checks passed using the actual licensed moving-weapon clip, real models and temporal engine, signed outbound HTTP on explicit loopback development transport, private API, two separately signed-in HTTP cookie sessions, acknowledge/dismiss, audit, database reopen and an actual annotated preview matching a target model sample.
- `docs/evidence/v03-2026-11-03/edge-fire-https.json`:18 checks passed through actual certificate-verified HTTPS, including rejection of the untrusted test certificate. The flame fixture is a licensed real photograph repeated as video. This proves inference/integration on that selected fixture, not natural-motion fire acceptance.
- `docs/evidence/v03-2026-11-03/edge-smoke-https.json`:18 checks passed with the corresponding real smoke model and licensed repeated-still fixture through HTTPS, signed metadata, review and persistence. Moving-smoke reliability remains unresolved.

The HTTPS verifier creates an isolated test certificate/CA under project `work/`, configures client trust only for that process, and does not modify system trust. No private camera, Internet upload, recording or saved image is involved in these checks. Two HTTP sessions demonstrate account/store consistency; they are not physical Android/iOS/Windows acceptance. Base44 deployment and browser layout acceptance are reported separately by their own executed tests.

Reproduce with `.venv/bin/python tools/verify_connected_edge_v03.py`, or select `--https --video data/v02-demo/fire_repeated_still.mp4 --detectors fire_smoke --category fire --output <new project-relative report path>`. Preserve previous evidence by choosing a fresh output filename. These fixtures remain selected development examples with retained false positives/misses; no broad safety-detector reliability claim follows.
