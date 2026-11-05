# SENTINAL V0.3 Base44 command center

## Verified hosted application

- Public website: https://sentinal-command-center-df4fc282.base44.app
- Private dashboard: https://sentinal-command-center-df4fc282.base44.app/app.html
- App ID: `6aea0ba86746c1a3df4fc282`.
- Source: `frontend/command-center/` in this existing SENTINAL project.

These URLs were published and exercised in actual Chrome on November 4, 2026. The local Python engine remains independent of Base44. The local connected backend and this cloud backend are selectable operational authorities; SQLite is not automatically synchronized bidirectionally. Cloud review decisions remain authoritative in the cloud and do not silently rewrite the desktop incident database.

## Sign in and provision access

Open the dashboard and select **Continue with Google**. The verified app owner has administrator access. Other authenticated native Base44 accounts have no SENTINAL access until an administrator grants their email an enabled `admin`, `operator`, or `viewer` membership through Administration. This form does not collect Base44 passwords or automatically send invitations. Users sign in through Base44 separately. Viewers can read; operators can review; administrators manage memberships, device credentials and retention. Direct entity reads/writes are denied by entity rules; authorized operations pass through backend functions and native account membership checks.

In Administration, register an authorized edge device. Its generated secret is returned once. Keep it in a private local configuration file, never Git, Drive snapshots, browser URLs or screenshots. Device registration does not start cameras. Explicitly start the selected authorized source in the desktop application or monitor command. Camera IDs are scoped to the paired device. Disable a device to reject new signed requests.

A private edge configuration uses the published HTTPS origin, its device ID and secret, and `ingest_path: "/functions/ingest"`. Existing local backend configurations retain `/api/edge/events`. The signed logical path is `/api/edge/events` for both transports; changing the physical endpoint does not change the protocol signature.

## Actual demonstration

1. Open the public website, then the private dashboard, select **Continue with Google**, and choose your authorized account.
2. Pair the authorized Mac edge device, storing its configuration only under `config/connected/` with owner-only access.
3. Start the installed detector against the legally sourced moving weapon fixture, or explicitly select an authorized live source. The prerecorded fallback is `data/v02-demo/weapon_range_motion.mp4`.
4. Observe actual possible-weapon incidents, scores, model version and camera ID in Incident Center. No footage is uploaded by this cloud connector.
5. Acknowledge an incident, add a review note, then dismiss the known safe demonstration. A second signed-in browser sees the persisted decision after refresh. Audit history records both actions.
6. Open AI Intelligence and Camera Management to inspect model and source health. A stopped source is not represented as active monitoring.

Example prerecorded, metadata-only invocation from the project root after activating its environment:

```sh
.venv/bin/python -m sentinal.connected.monitor \
  --config config/connected/base44-edge.json \
  --video data/v02-demo/weapon_range_motion.mp4 \
  --camera-id HACKATHON-WEAPON \
  --name 'Authorized public moving-weapon fixture' \
  --detectors weapons --alert-confidence .35 --display-confidence .25 \
  --persistence .3 --max-gap 2 --loop --max-seconds 25 \
  --report docs/evidence/v03-2026-11-03/base44-edge-weapon.json
```

The fixture and model must already exist locally; this command is not an automatic download. See the model manifest for provenance and licensing. The detector is GingerBrains/YOLOv8s-weapons, model revision `ab6f53c8…`, not a certified weapon classifier. Its detections are uncertain observations requiring human review. The cloud does not infer intent.

## Privacy and protocol

Only structured incident/model/camera/health metadata is sent outbound over HTTPS. Evidence upload, external notifications and remote video delivery are disabled. Live Monitoring clearly reports that no authorized remote video gateway is configured. No raw RTSP credentials or private CCTV frames are embedded in the website. Local preview remains a separate local feature.

Requests use the existing SENTINAL HMAC protocol with a SHA-256-derived device signing key, bounded timestamps (180 seconds), persisted nonces and event/body receipts. A valid event retried under a fresh nonce is acknowledged without duplicating an incident or overwriting human review; nonce reuse and changed content under an existing event ID are rejected. Signed requests still require an enabled device and device-owned camera IDs.

The single authoritative state record uses the provider's conditional `updateMany` on record ID and revision, with retry on competing writes. Nonces, incidents, human decisions and audit entries are committed in the same compare-and-set operation. Actual concurrent provider writes were tested: exactly one writer won the same revision. Model confidence is an uncalibrated score, not a probability of danger.

## Prototype limits

This deployment is one organization per Base44 app. Limits are explicit: 200 incidents, 32 devices, 32 memberships, 1,000 audit entries, 256 incident receipts and 2,048 valid nonce entries. A full live nonce ledger rejects requests with 429 rather than evicting replay protection. Old entries expire only outside the accepted timestamp window. Heartbeat duplicate receipts retain the last 32 events per device, and old heartbeat timestamps cannot replace newer health. Reported/received health older than 45 seconds is offline. This is a bounded prototype, not an indefinitely retained forensic journal or scalable multi-tenant backend.

Retention is configurable from 1 to 365 days (default 7); pruning runs on incoming events and authorized reads, not a guaranteed background deletion schedule. No cloud evidence is retained because cloud evidence uploads are disabled. Plan quotas and provider outages may affect delivery; the edge outbox retries bounded deliveries and exposes failures. No public sharing of private incidents is supported. Native mobile packaging, physical iOS/Android/Windows verification and a browser-compatible video gateway remain unverified/unimplemented.

## Rebuild and publish

Node 24 is used. Dependencies are pinned: Base44 SDK 0.8.40 and Vite 8.3.5. Vite's production build passed; these are frontend tools, not the continuous-inference runtime. Build from the existing project root:

```sh
PROJECT_DIR="$PWD"
. "$PROJECT_DIR/runtime-env.sh"
cd frontend/command-center
npm ci
npm test
npm run build
```

`sync-assets.mjs` copies/adapts the current root `web/` assets into this Base44 frontend, preserving the source dashboard while replacing local password forms with native Base44 authentication and explicit membership/device provisioning. Do not independently edit generated copies without updating this adapter. The linked `.app.jsonc` and private credentials are excluded from snapshots; linking a new checkout must target the existing app ID, not create a duplicate application.

Official CLI deployment from `frontend/command-center/` after verified owner sign-in and linking:

```sh
BASE44_DISABLE_TELEMETRY=1 node --import ../../tools/base44_local_storage.mjs \
  ../../work/base44-tools/node_modules/base44/bin/run.js functions deploy
BASE44_DISABLE_TELEMETRY=1 node --import ../../tools/base44_local_storage.mjs \
  ../../work/base44-tools/node_modules/base44/bin/run.js site deploy --no-build --yes --publish
```

The helper scopes CLI state inside the project without changing the machine's HOME. Backend provisioning requires the existing `CommandState` record and protected `SENTINAL_STATE_ID` / `SENTINAL_OWNER_EMAIL` secrets; do not place these protected provisioning files in Git. The entity schema is deny-by-default. Normal functions use native user context and a guarded service role. Do not invoke functions through `app.base44.com`; use the app's actual published subdomain. The initial platform-domain request correctly failed with 403 and is preserved as failed evidence.

## Executed verification

Evidence is in `docs/evidence/v03-2026-11-03/` (the folder name is the development milestone date, not a claim all tests ran that day).

- `base44-node-tests.txt`: 21 unit/security-contract tests passed. Mock CAS adapter coverage is distinguished from actual provider coverage below.
- `base44-authority.json`: 9 actual provider checks passed, including native owner authentication, entity access denial, anonymous function denial and concurrent compare-and-set behavior.
- `base44-replay.json`: 3 actual signed delivery checks passed using an already delivered real model alert: duplicate acknowledgment, nonce rejection and changed-body rejection.
- `base44-hosted-browser.json`: 24 actual hosted Chrome checks passed, including desktop 1440×1000 and mobile-size 390×844 layouts, real model incident visibility, acknowledgment/dismissal synchronization and sign-out. Two isolated browser contexts used the same authorized app-scoped owner identity obtained through the official CLI exchange. This does not claim two independent Google sign-in flows or physical mobile hardware testing.
- `base44-post-review.json`: read-only post-review audit and UI evidence; see its recorded outcome.
- `base44-edge-weapon.json`: actual MPS inference over 25.50 seconds processed 722 frames, produced 121 hazard samples, 2 candidates and 2 alerts; 14/14 metadata deliveries succeeded with zero pending/failed. Mean inference latency was 27.12 ms and observed processing throughput 28.31 FPS on this fixture. These are measured fixture results, not a fixed live-camera/cloud UI frame-rate guarantee.
- `base44-edge-weapon-browser-fixture.json`: second actual moving-fixture run produced one additional real alert for the hosted review test; 6/6 deliveries succeeded.

Reproducible helpers: `frontend/command-center/tests/remote-authority.mjs`, `frontend/command-center/tests/hosted-browser.mjs`, `frontend/command-center/tests/post-review.mjs`, and `tools/verify_base44_replay_v03.py`. Run from the project root with protected authorized configuration. The hosted browser test requires a new actual ALERTED incident because it performs real acknowledgment/dismissal. The authority verifier increments only the state revision for its concurrent CAS check and should run while operators are idle. The replay verifier reuses an existing real delivered incident, not fabricated inference.

Earlier platform-domain authority failure and two browser harness failures (an optimistic review-version conflict and navigation-readiness wait) are retained under `base44-authority-platform-initial.json` and `base44-hosted-browser-initial-*.json`. The final passing run followed corrected test readiness checks; these failures were not silently relabeled as successes. Existing desktop/camera/fire/smoke tests are documented in the main V0.3 verification report and are separate from this cloud scope.

Official references: [Base44 developer documentation](https://docs.base44.com/), [Base44 CLI package](https://www.npmjs.com/package/base44), [Base44 SDK](https://www.npmjs.com/package/@base44/sdk), [Vite releases](https://github.com/vitejs/vite/releases). Model sources and licenses remain in the project model manifest.


## V0.3.1 access correction — November 4, 2026

The owner reported that the public website opened but the dashboard sign-in failed. A fresh browser reproduced the defect: `redirectToLogin()` navigated to `/login`, which this static hosting deployment served as the public landing page. The earlier valid-token browser checks did not cover this fresh sign-in path. This has been corrected using the officially supported `base44.auth.loginWithProvider('google', returnURL)` entry. The application owner subsequently confirmed that the dashboard opens through Google using the authorized professional account. No account memberships, entity rules or incident data were changed.

A fast initial click could also occur before the frontend module attached its handler. Sign-in and retry buttons now start disabled and become usable when the handlers are ready. Existing `/login` bookmarks recover to `/app.html`. Expired/invalid sessions, permission failures and service/network failures show actionable feedback; retry and sign-out/account-switch controls are available rather than silently returning to a blank login state. The callback continues to consume the native Base44 token and remove it from the browser address.

Fresh evidence is under `docs/evidence/v03-access-app-2026-11-04/`: successful production build, 21 passing security/unit checks, publication output, the reproduced old-route failure, Google's actual visible sign-in page, and `base44-access-browser.json` for the final callback/mobile/session-recovery outcome. Earlier unsuccessful Google load/readiness attempts are retained as `base44-access-browser-*-initial.json`; the later independent callback-only run explicitly declares that Google consent is not being automated. Native consent completion is supported by the owner's confirmation, not a fabricated automated login claim.

Repeat the bounded callback/recovery check from the project root with the already authorized private app-token configuration:

```sh
node frontend/command-center/tests/access-browser.mjs --callback-only
```

Omit `--callback-only` to additionally navigate a fresh browser to Google's sign-in page; it does not enter passwords or approve consent. Google may apply independent browser/identity-provider checks. See the [official Base44 authentication SDK reference](https://docs.base44.com/developers/references/sdk/docs/interfaces/auth#loginwithprovider).
