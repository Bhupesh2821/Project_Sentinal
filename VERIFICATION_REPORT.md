# SENTINAL V0.3.2 verification

November 5, 2026. The owner confirmed live built-in Mac camera video in the updated native app. The verified Base44 dashboard remains available through Continue with Google. [Private dashboard](https://sentinal-command-center-df4fc282.base44.app/app.html)

Open `dist/SENTINAL.app` in the canonical project. It uses this project's environment, models and compatible Python framework. The full project ZIP includes the same locally signed bundle at `SENTINAL/SENTINAL.app`.

The app window now handles camera consent on explicit Start or Refresh, before the background capture worker starts. Single-source and camera-wall starts share the permission request. Stop, tile Stop, Close and source or selection changes cancel a pending start. The app revalidates the selected camera identity. File and RTSP inputs go directly to their existing source adapters. [Qt permission documentation](https://doc.qt.io/qt-6/permissions.html)

| Check | Result |
| --- | --- |
| Full Python regression | 632 passed, zero failed or skipped, 79.56 seconds. [Final log](docs/evidence/v032-2026-11-05/pytest-final.txt) |
| Focused consent and controls | 101 passed in 5.63 seconds. The tests use fake permission states and capture workers. [Focused log](docs/evidence/v032-2026-11-05/focused-consent-tests.txt) |
| Missing-camera guidance and consent | 49 passed in 2.22 seconds. [Focused log](docs/evidence/v032-2026-11-05/guidance-tests.txt) |
| Native app | 23 checks passed, including Cocoa launch, read-only permission query, real recorded-video inference and alert, Stop and normal Quit. [Native evidence](docs/evidence/v032-2026-11-05/native-app.json) |
| Built-in Mac camera | The owner reported live video after the first-use flow. [On-device confirmation](docs/evidence/v032-2026-11-05/user-camera-confirmation.json) |

The read-only Cocoa query returned Undetermined before the owner's consent. The native test used the public moving-weapon fixture. The development checks collected no private camera frames. The owner confirmation covers live video on this Mac. Physical iPhone/CCTV, hosted video and installation on another Mac remain outside the verified scope.

The initial full run had 630 passes and two missing-camera guidance failures. The app now shows the exact-selection guidance when Start has no selected device. The focused and full reruns passed. The native prerecorded test and owner's live test preceded that guidance-only repair. [Initial log](docs/evidence/v032-2026-11-05/pytest-initial-guidance.txt)

Model accuracy remains experimental. The earlier reports contain the model provenance, real hosted incident review and measured inference performance. The published source commit and Drive checksums belong to the release's companion manifest. [V0.3.1 verification](docs/verification/V0.3.1-VERIFICATION_REPORT.md) · [Model reliability evaluation](docs/DETECTION_RELIABILITY_V021.md)
