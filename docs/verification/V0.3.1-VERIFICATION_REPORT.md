# SENTINAL V0.3.1 — dashboard access repair and Mac app verification

Report date: November 4, 2026. **The owner confirmed that the dashboard now opens. The native Mac app was built and passed actual recorded-video operation.** This remains a development prototype with the existing detection errors and hardware limits.

Canonical root: `/Users/prabhuram04yahoo.com/Documents/Bhupesh/Projects/ProjectSentinal`. The original V0.3.0 source commit, full archive and reports are preserved; the pre-change record is `history/implementation-v03-access-app-2026-11-04/baseline.json`.

## Dashboard correction

The old button called the SDK's generic `/login` route. On this CLI static deployment, that address served the public landing page, so it never reached authentication. The earlier hosted tests used an existing app-scoped session and missed the first-login failure.

V0.3.1 uses the supported Google provider entry, recovers old login bookmarks, waits until sign-in handlers are ready, and exposes Retry connection, sign-out/switch-account and understandable session/network/permission errors. No native memberships, entity permissions or incident records were weakened or replaced. The user independently confirmed **“Dashboard opens”** with the configured owner account.

Public website: [SENTINAL](https://sentinal-command-center-df4fc282.base44.app). Private dashboard: [Command center](https://sentinal-command-center-df4fc282.base44.app/app.html). Select **Continue with Google** and your authorized account. Video inference remains local.

## Mac application

Open **`dist/SENTINAL.app`** in the development project. The complete V0.3.1 project ZIP includes the same bundle as **`SENTINAL/SENTINAL.app`**, beside the source. It opens the actual PySide desktop without requiring a manually started terminal service.

This arm64 native app uses the existing project `.venv`, source, models and compatible Python framework. Keep the project intact. It is locally ad-hoc signed, with an original icon and explicit camera/local-network purpose text; it is not a portable standalone installer or Apple-notarized distribution. No private stores, models or environment copies were embedded in the small native bundle. [Full app instructions](docs/MACOS_APP.md).

## Executed checks

| Check | Actual result and scope |
| --- | --- |
| Full Python regression |**599 passed,0failed/skipped,83.44s**, including existing Vision Core, connected services, release policy, new native-build boundaries and incremental Git tests. `docs/evidence/v031-2026-11-04/pytest-final.txt`. |
| Actual native app |**22checks passed** through LaunchServices/Cocoa: correct identity/version, real spawned child through `.venv/bin/python`, no recursive GUI, deliberate Start, genuine moving-video inference, actual possible-handgun box/score/temporal alert, Stop/source release and accepted normal macOS Quit. Camera, recording, sound and outbound delivery stayed off. `native-app.json` and public-only `native-app-video.png` in the same folder. |
| Hosted callback/recovery |**18checks passed**: public CTA, actual owner callback and incident access, URL-token removal/storage, actual owner identity, mobile layout, invalid-session private-screen protection, retry, switch-account and old-link recovery; no uncaught page errors. `docs/evidence/v03-access-app-2026-11-04/base44-access-browser.json`. |
| First native sign-in |Fresh browser reached the actual Google email sign-in page through the supported provider route; no passwords or consent were automated. The owner's own successful sign-in confirmation is separate evidence. `base44-native-signin-current.json` and `user-access-confirmation.json`. |
| Frontend security/unit tests |**21passed,0failed/skipped**; actual build/publication output retained in the access evidence folder. These component checks do not replace the live sign-in/user confirmation. |
| Release/app boundaries |**41focused tests passed1.85s**, including existing public asset policy, native-file whitelist, stale bootstrap/symlink/private-file rejection and build output boundaries. `docs/evidence/v031-2026-11-04/app-package-tests.txt`. |
| Incremental Git safety |**23focused tests passed13.79s**, including real isolated bare-Git transport, exact parent chain, unchanged working HEAD/index/user files, concurrent-ref protection, source/remote drift rejection and non-force fast-forward/readback. `git-update-tests.txt` in the same folder. |

Earlier failed compile/link, Quit transport and browser readiness/display-name assertions are preserved separately. The initial Quit harness received a nonzero AppleScript transport result despite the app's normal clean exit; the accepted final normal-quit request was checked explicitly. Browser tests were corrected to wait for the actual state and validate identity through authenticated User/me, rather than expecting an email in a display-name label. No unsuccessful run was relabelled as passing.

The native test used only the attributed public-domain moving-range fixture; it saved no private camera image and enabled no network delivery. The actual model score was0.60619, model revision `ab6f53c8d18d77d799fa70a46adea646d7bb4499`. The inherited sleeve/person misclassification remains visible; this package does not improve model accuracy.

## Limits and preserved evidence

- Native app camera permissions under its new identity, physical iPhone/CCTV and another-Mac installation remain separate on-device checks. No camera was opened during the new native acceptance run.
- The app is built for the current development runtime. Rebuild from source for another compatible environment; moving only the bundle does not install dependencies or models.
- Hosted CCTV video, compiled Windows/mobile packages, external notifications, unattended-item/GHS modules and certified safety reliability remain unimplemented/unverified.
- Weapon/knife/fire/smoke false positives and misses are unchanged. The retained24-scene study is not independent field validation; toy-versus-real and loose-blade recognition remain unreliable. See `docs/DETECTION_RELIABILITY_V021.md`.
- The prior actual real-inference HTTP/HTTPS/cloud-to-review results and measured performance remain in [V0.3.0 verification](docs/verification/V0.3.0-VERIFICATION_REPORT.md). They are not recast as new hardware or accuracy tests.

Exact appended Git commit, package checksums and Drive readbacks are recorded in the V0.3.1 delivery manifest/receipt beside the release. The prior V0.3.0 archive is preserved. Private configuration, accounts, recordings, operational databases and caches remain excluded from source and distribution.
