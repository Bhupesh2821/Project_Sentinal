# SENTINAL macOS application

The actual macOS application is **`dist/SENTINAL.app`** inside this development project. The V0.3.2 project ZIP places the same bundle at **`SENTINAL/SENTINAL.app`**, beside its source and launcher scripts. In Finder, open the project, open `dist`, then double-click **SENTINAL**. It opens the existing desktop directly, without manually starting a terminal service. Camera capture, recording, sound and outbound metadata remain off until you enable the relevant controls and press Start.

This is a **project-linked native app**, not a portable standalone installer. Its small native Mach-O executable embeds the installed Python framework and loads this project's existing `.venv`, source and models. Keep the full project and its environment in place. It can find the project beside/above the bundle; its saved local project location is a fallback. Moving only the app to a different computer does not install Python, dependencies or models.

The bundle has its own SENTINAL icon, application identifier, version, camera permission text and local-network purpose text. A camera request still requires explicit monitoring. It does not request microphone recording. The local build has an ad-hoc code signature, not a Developer ID signature or Apple notarization. The owner confirmed live Mac video in V0.3.2 after using the first-use consent flow. See the current verification report.

## Use

1. Double-click `dist/SENTINAL.app`.
2. Select the exact authorized camera, imported video or compatible saved network source. The app does not substitute an unavailable camera.
3. Choose detectors/settings and press Start. Stop releases the selected source.
4. For the hosted dashboard, use the separately documented Base44 sign-in and pair the intended backend through **Connected command center…**. The app does not enable that network connection merely by opening.
5. Quit normally through the application menu or Command-Q.

All existing project files, models, databases, imported videos and private credentials stay in the canonical project folder. The bundle copies none of those private stores. Diagnostic startup output is in `logs/app-launcher.log`, with a bounded previous log; normal technical logging remains in the existing project logging module.

## Build again

Use the installed macOS command-line compiler and this project's compatible framework Python. From the project root:

```sh
PROJECT_DIR="$PWD"
. "$PROJECT_DIR/runtime-env.sh"
.venv/bin/python tools/build_macos_app.py
```

The builder writes only within this project. An existing destination bundle is preserved under `history/macos-app/` before replacement. It renders the project's original vector icon using the already installed Qt SVG renderer and creates a verified local ad-hoc signature. No global dependency or system configuration is installed or changed.

Native source is in `tools/macos/launcher.m`; its guarded Python bootstrap is `tools/macos/bootstrap.py`. The process uses the real `.venv/bin/python` for subprocesses and multiprocessing. Spawned children do not recursively open another desktop.

## Executed validation

`docs/evidence/v031-2026-11-04/native-app.json` records 22 successful checks through actual macOS LaunchServices and Cocoa:

- Actual app identity/version and visible native desktop.
- Real spawned child uses the project Python without importing/opening a second Qt application.
- Capture waits for an explicit Start; camera, recording, evidence, sound and network delivery stay off.
- The attributed public-domain moving range video produces real GingerBrains YOLOv8s predictions, a visible possible-handgun box/score and a temporally confirmed possible alert.
- Stop releases the video source; normal macOS Quit is accepted and the application exits cleanly.

The saved `native-app-video.png` contains only the authorized public fixture's actual rendered video panel. It is not a live camera image. This selected successful demonstration does not improve or establish broad detector accuracy. Two separate pytest boundary checks passed; they do not substitute for the actual native execution.

The initial C-API compile/link setup and initial AppleScript Quit harness failure were corrected and preserved under project `work/` and the initial native JSON. The Qt app had exited normally, but the first external AppleScript transport returned nonzero, so that complete initial orchestration was not marked passed. The final verifier sends the normal `NSRunningApplication.terminate` request, never `forceTerminate`, and checks the actual clean exit.

To repeat the bounded actual-video test, choose a new evidence filename:

```sh
.venv/bin/python tools/verify_macos_app.py \
  --output docs/evidence/v031-2026-11-04/native-app-rerun.json
```

This explicit verification command starts only the licensed prerecorded demo. Normal app launch does not start any source. Signed portable distribution, another-Mac installation and physical iPhone/CCTV acceptance remain separate work.
