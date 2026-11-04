# SENTINAL V0.3 connected API

The Python camera/inference engine remains independent. The connected service accepts explicitly enabled, signed metadata from registered edge devices. It serves the public website and an authenticated dashboard on the same origin. It never opens a camera. Ordinary startup does not enable remote event delivery, evidence upload or video transfer.

This backend is implemented with Python's standard library and existing SQLite. It is a development/hackathon service, not a production security certification. Base44 hosting/authentication is a separate integration and is not established by a successful localhost API test.

## Start and provision

From the confirmed `ProjectSentinal` root, set `PROJECT_DIR="$PWD"` and source `runtime-env.sh`. Use the project's Python:

```sh
.venv/bin/python -m sentinal.connected.server init --username owner
.venv/bin/python -m sentinal.connected.server serve --host 127.0.0.1 --port 8765
```

`init` prompts for a password of at least 12 characters. There is no built-in/default account or password. A locally controlled `--password-file` is available for automated acceptance tests; keep such files owner-only and outside Git. Additional `init --username <name> --role operator` or `--role viewer` accounts use the same organization by default. Browser administrators can also create accounts in their own organization through the protected user API.

Data defaults to `recordings/connected/server.sqlite3` under the project. `--data-dir` must remain inside the project. The database directory is owner-only and the database mode is0600. Passwords use salted, versioned scrypt hashes with N=16384,r=8,p=5, one of the configurations in the [OWASP password-storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt). Session bearer tokens are stored only as SHA256 hashes. Sessions expire after eight hours. Temporary initial prototype password hashes remain verifiable and are upgraded after successful login.

Provision an edge device locally after creating its strong secret in an owner-only project file:

```sh
.venv/bin/python -m sentinal.connected.server device --device-id mac-edge --name "Presentation Mac" --secret-file config/connected/device-secret.txt
```

The server stores a SHA256-derived signing key. **That derived key is still sufficient to sign requests: it is bearer-equivalent sensitive material, not encryption or protection against a fully compromised database.** Protect the database/backups. Device secrets and signing keys are never returned by the web API. Admins can revoke a device; registration does not silently replace existing credentials. Secret rotation/re-enrollment needs an explicit future administrative flow.

## Browser authentication and roles

| Endpoint | Result / permission |
| --- | --- |
| `GET /api/health` | Public service availability/schema and explicit local-preview flag; no incident/camera names |
| `POST /api/login` | JSON `{username,password}`; returns `{user,csrf_token}` and an HttpOnly,SameSite=Strict session cookie |
| `GET /api/session` | Authenticated `{user:{id,username,role,organization},csrf_token}` |
| `POST /api/logout` | Current session only; accepts an empty JSON object or no body |
| `GET /api/summary` | Organization-scoped actual counts |
| `GET /api/incidents` | `{items:[...]}`; optional exact `status`, `category`, `severity`, `search`, `limit`1–200 |
| `GET /api/incidents/<id>` | Scoped incident DTO or404 |
| `GET /api/incidents/<id>/audit` | `{items:[...]}`; scoped to that incident |
| `POST /api/incidents/<id>/review` | Operator/admin only: `{status,note,expected_version}` |
| `GET /api/devices` | Scoped registered devices and actual received heartbeat metadata |
| `POST /api/devices/<id>/disable` | Admin only, `{}`; revokes the signing key and clears its RAM previews |
| `GET /api/cameras` | Scoped safe camera metadata and explicit preview availability |
| `GET /api/models` | Scoped edge-reported model provenance/classes/health; not invented installed-model data |
| `GET /api/users` | Admin only; no password hashes |
| `POST /api/users` | Admin only, `{username,password,role}`; organization comes from the authenticated admin |
| `GET /api/audit` | Admin only; organization-scoped recent audit |
| `GET /api/settings` | Admin only; current retention and unsupported evidence/notification flags |
| `PATCH /api/settings` | Admin only, `{retention_days:<integer1–365>}`; applies retention immediately |

All browser mutations require an exact same-origin `Origin` header. After login, send `X-CSRF-Token` on browser mutations. Sign-in itself checks Origin to prevent login CSRF. The server validates Host, rejects cross-origin preflights, and emits no CORS allowance. Browser tokens are not placed in URLs or logs. Session cookies receive `Secure` under TLS/configured HTTPS origin. Private responses and previews use `Cache-Control:no-store`; a service worker must not cache API data, app sessions or previews.

A viewer can read their organization's incidents, health and per-incident audit, but cannot review. Operators can review; administrative account/policy/device actions require admin. Organization assignment comes from a stored user/device record, never an event payload or user-supplied query parameter. IDs in another organization return404. Incident review is an atomic compare-and-update: a stale expected version returns409. Allowed human actions are ACKNOWLEDGED,VERIFIED,DISMISSED,CLOSED, following the existing incident state machine. A delayed edge update never overwrites a human review decision.

## Signed edge metadata

`POST /api/edge/events` accepts at most128KiB of UTF-8 JSON. No frame, image, video, stream URL, password, arbitrary evidence URL or credential field is accepted. Unknown/duplicate JSON members, non-finite numbers, unsupported types, invalid boxes/classes/timestamps and forged review states are rejected. Camera lists are capped at32 entries, model lists at16, and supported class lists at1000 per model.

Use `sentinal.connected.protocol.canonical_json(event)` and `sign_request(secret,device_id,body)` in the edge adapter. Example field shapes:

```json
{
  "schema_version": 1,
  "event_id": "a stable canonical UUID for this source event",
  "kind": "incident",
  "device_id": "registered-device-id",
  "occurred_at": "timezone-aware actual event timestamp",
  "incident": "the exact existing Incident.to_dict() object"
}
```

This JSON is a schema illustration, not a valid/sample detection or a persisted incident. Incident fields are the existing Vision Core DTO: incident/source/session IDs, category,status,confidence,severity,model ID/version,box,optional tracking ID,first/last observation,alert timestamp and latency. Edge states are restricted to OBSERVED,CANDIDATE,ALERTED. A source must never claim a human review decision.

A heartbeat uses the same core envelope with `kind:"heartbeat"` and replaces `incident` with:

- `health`: actual `status`(idle/running/error/reconnecting), optional measured processing_fps,inference_ms,memory_rss_mb and a bounded sanitized message.
- `cameras`: camera_id,name,status and optional actual last_frame_at. No network endpoint or password.
- `models`: model_id,version,classes,status and optional processing device.

Omit unavailable numeric values rather than sending null or inventing measurements. A device without a fresh heartbeat is offline after45seconds, including a queued old heartbeat received recently. Delayed heartbeats cannot overwrite newer device health. Models/cameras from stale devices are explicitly unavailable/offline; original reported values remain identified as historical.

Headers are `X-Sentinal-Device`, `X-Sentinal-Timestamp`(Unix seconds), `X-Sentinal-Nonce`(32–128lowercase hex characters), and `X-Sentinal-Signature`(lowercase SHA256 HMAC hex). The signature input is:

```text
SENTINAL1
POST
/api/edge/events
<device_id>
<timestamp>
<nonce>
<sha256_of_exact_request_body>
```

The HMAC key is SHA256(secret UTF8). Each line is separated by LF, with no final LF. Timestamp skew is limited to90seconds. Nonces are retained persistently for180seconds across service restart; each retry must use a fresh nonce/signature. Event IDs remain stable across retries. Same ID/exact body yields200 and `duplicate:true`; different content for an accepted ID yields409. New events yield201. Success always includes `{ok:true,event_id,duplicate}` and incident_id for a newly processed incident. A client must verify ok/event_id before removing its outbox entry. Errors use `{error:<understandable message>}`.429includesRetry-After.

Only an explicitly configured HTTPS target may receive remote delivery. The edge adapter may permit an explicit loopback HTTP development exception. The server also refuses non-loopback HTTP serving: use configured TLS certificate/key, or an explicitly configured HTTPS reverse-proxy origin. Reverse proxy, public DNS, managed hosting and certificate operations need their own verification; the localhost tests do not establish production deployment. No open inbound route to a CCTV network is created.

## Optional local preview

Default disabled. Start a loopback service with `--allow-local-preview` only when the operator explicitly authorizes local video transfer. This flag is refused for non-loopback serving or an external public origin. It is independent of the metadata outbox and does not authorize uploading video to Base44/cloud storage.

`POST /api/edge/preview` uses the same signing helper with `path='/api/edge/preview'`. The exact JSON fields are device_id,camera_id,captured_at,jpeg_base64. Maximum encoded body512KiB, maximum decoded JPEG384KiB. The camera must already belong to that registered device and be reported active in a heartbeat. The frame timestamp must be within3seconds of server time. Marker/type/size checks bound a trusted edge JPEG; this is not a general hostile-image validation service.

`GET /api/cameras/<camera_id>/preview.jpg` requires the same organization/session authorization as incident data. Frames exist only in a bounded32-camera RAM map, expire after3seconds, and disappear on unavailable camera/device state or service shutdown. Nothing is written as an image to disk. Headers identify the actual captured timestamp and prohibit caching. This is an authenticated recent-frame preview, not a WebRTC/HLS gateway, continuous browser inference or publicly exposed RTSP endpoint.

## Persistence, bounds and limitations

The service is authoritative for connected human review, accounts, registered edge keys, incident versions and audit. The existing desktop incident store remains authoritative for its local session/evidence. Explicit outbound event IDs connect these stores; there is no uncontrolled bidirectional database synchronization or automatic overwrite of desktop review state.

Connected incidents default to seven-day retention, configurable1–365days, and at most10000per organization. Retention is enforced on ingestion/policy changes. Audit is capped at20000rows per organization; receipts at100000; replay nonces at60000; rate buckets at10000. These bounded prototype policies are not immutable audit or guaranteed secure erasure. User/account/device records are retained until an explicit administrative migration; changing retention does not erase credentials. Evidence uploads and external notifications are unavailable in this backend and the API reports those flags as false.

The listener caps concurrent request handlers at32, request-read timeout10seconds, metadata/body lengths, authentication attempts and device request rates. Static serving uses an explicit file allowlist; source/config/database/private media are never served. No insecure directory listing is enabled. Security headers restrict scripts/styles/connections to the same origin; no inline script exemption is added.

The tests use separate project-local stores and identified synthetic DTOs for authentication/persistence/failure contracts, plus actual HTTP and HTTPS transport. Real AI-to-dashboard testing belongs to the integrated application acceptance report; unit incidents do not prove firearm or fire accuracy. No physical iOS/Android/Windows acceptance, public Base44 deployment, MFA, password recovery, production-grade key management, multi-server HA, certified fire detection or new advanced hazard model is implied by this API.
