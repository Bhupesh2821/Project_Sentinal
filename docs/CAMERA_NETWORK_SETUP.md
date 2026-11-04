# SENTINAL V0.1.2 — Mac, iPhone and network CCTV setup

Open `launch.command` in `/Users/prabhuram04yahoo.com/Documents/Bhupesh/Projects/Project Sentinal`. The application opens in standby. This version monitors one source at a time.

## Choose the Mac camera or iPhone

1. Select **Camera** under **Monitoring source**.
2. Choose the named **Mac camera**, **Phone camera** or **External camera** entry.
3. Press **Start monitoring**.
4. To change cameras, press **Stop monitoring**, wait for the source to release, choose another device, then press **Start monitoring** again.

SENTINAL opens the exact selected device identity. A change in camera-list order does not turn a Mac selection into an iPhone selection. The built-in camera may be preselected initially, but opening the application or refreshing devices does not activate it. If the selected camera disappears, monitoring reports the failure and does not substitute another camera. Reconnect and select the device again, or explicitly choose another one.

Use **↻** to refresh the device names without opening a capture session. If a device is missing or cannot start, check its connection, close other apps holding it, and check camera access for the launcher under **System Settings → Privacy & Security → Camera**.

## Make your iPhone available

Apple Continuity Camera makes a compatible iPhone available as a Mac webcam. Use the same Apple Account with two-factor authentication, enable Continuity Camera on the phone, keep Wi-Fi and Bluetooth on, and place both devices nearby. Mount the phone securely with the rear cameras unobstructed; it normally stays locked during webcam use. A USB connection is also supported when the iPhone trusts the Mac. Follow [Apple's current Continuity Camera requirements and troubleshooting](https://support.apple.com/en-us/102546).

On the iPhone, check **Settings → General → AirPlay & Continuity** (or **AirPlay & Handoff**) → **Continuity Camera**. Refresh SENTINAL's camera list, choose the **Phone camera** entry and press **Start monitoring**. Calls, unlocking the phone or disconnecting it can interrupt capture. Restore the connection and select it again. Enabling Continuity Camera does not make SENTINAL select the phone automatically.

## Find an ONVIF CCTV camera

1. Connect the Mac and camera/NVR to the same reachable network. Wired and Wi-Fi devices can both work if the network permits communication.
2. Enable ONVIF in the camera/NVR settings if required. Some devices have a separate ONVIF account.
3. Choose **Network camera**, then **Find / connect CCTV…**.
4. Click **Find cameras on this network** and select a returned camera service.
5. Enter its ONVIF username and password in the separate fields. Click **Get video streams**.
6. Choose a returned profile and click **Use selected stream**.
7. Back in the monitoring window, press **Start monitoring** to open and analyze that feed.

Discovery and profile lookup contact the device for metadata. They do not start video monitoring. **Use selected stream** fills the main window; **Start monitoring** opens its video connection.

Discovery uses bounded IPv4 WS-Discovery multicast on the active network interface. It runs only when clicked and does not scan every IP address. It can miss cameras with discovery disabled, blocked local-network access, separate VLANs or incompatible ONVIF services. The client implements selected ONVIF Media/Media2 operations and HTTP Basic/Digest plus WS-Security password-digest authentication. It is not an ONVIF-certified client; compatibility with every camera/NVR is not guaranteed. [ONVIF describes its IP video streaming interoperability model here](https://www.onvif.org/profiles/profile-s/).

## Connect manually

If discovery returns nothing, enter the actual ONVIF device-service address in the setup dialog. The common format `http://192.168.1.100/onvif/device_service` is an example, not your camera's address. Use the correct address and port from its settings or manual, enter credentials separately, then request its streams.

Alternatively, enter the actual **RTSP, RTSPS, HTTP or HTTPS video endpoint** directly in the main window's **Network camera** fields, add credentials if needed, and press **Start monitoring**. A camera's browser login page is usually not a video endpoint. Obtain the stream path from the manufacturer or NVR settings; channel paths and ports vary.

Wi-Fi connectivity alone does not provide a usable video stream. Proprietary cloud-only cameras, unsupported codecs/authentication, self-signed HTTPS certificates or different-server stream addresses can require device-specific configuration or a direct video address. A failed connection shows an error and releases the source so you can correct it and retry. An established feed interruption receives the configured bounded reconnect attempts; reconnecting starts a fresh tracking session.

## Local processing and stopping

Inference runs locally after installation. Network video is received from the endpoint you select; camera/video frames are not uploaded to an AI service. Mac/iPhone capture opens no microphone. Detection metadata recording is unchecked at launch and remains optional.

All project-owned code, models, configuration, imported videos, databases, diagnostics, temporary files and verification evidence stay inside `/Users/prabhuram04yahoo.com/Documents/Bhupesh/Projects/Project Sentinal`. Camera selection and network passwords stay in memory for the current application session. Network source labels omit credentials, paths and query values.

Press **Stop monitoring** to release the source. Closing SENTINAL also cancels outstanding camera-setup work. Read `VERIFICATION_REPORT.md` for dated executed checks and remaining physical-camera compatibility limits.
