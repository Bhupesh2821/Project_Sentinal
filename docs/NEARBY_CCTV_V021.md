# Nearby CCTV and multiple-camera selection

The Nearby CCTV window provides a refreshable list of compatible camera services that answer on the Mac's selected local network. It works on reachable Wi-Fi or Ethernet networks. Camera advertisements, successful authentication and receiving video are separate states; the list does not label a camera as monitoring merely because it replied.

## Find cameras

1. Connect the Mac and your authorized cameras/NVR to the same reachable network. A shared Wi-Fi name alone does not establish reachability when guest/client isolation or separate VLANs are enabled.
2. Open **Nearby CCTV…** from camera management, or the network-camera setup control in the main window.
3. Choose **Automatic route** or a specific active IPv4 interface/address. **Refresh networks** refreshes local interface metadata and does not open a camera.
4. Click **Refresh nearby CCTV list**. A bounded background ONVIF discovery request runs for about three seconds. Results show name, host and **ONVIF advertised**. Refresh replaces the old results rather than accumulating stale entries. No periodic background discovery, subnet/port scan, authentication bypass or video upload is performed.
5. Select a service, enter its legitimate ONVIF account and click **Get video streams**. Choose a returned stream and use it. Opening a source still requires explicit Start.

Some cameras disable ONVIF discovery or expose only a manufacturer/cloud interface. Client isolation, multicast filtering, a separate VLAN or denied macOS local-network access can hide a reachable camera from this list. The empty state explains these possibilities and supports manual authorized ONVIF or RTSP/HTTP entry. No reply is not proof that no cameras exist.

macOS may require permission for the application launching the Python process. Check **System Settings → Privacy & Security → Local Network** for the relevant launching application. SENTINAL does not change system permissions or firewall settings automatically. Discovery currently uses IPv4 ONVIF multicast; IPv6 discovery and general Wi-Fi access-point scanning are not implemented.

## Choose cameras together

Save each authorized camera with a clear name in **Camera management**. A discovered ONVIF stream fills the fields; saving remains explicit. If an NVR returns multiple channels/profiles, save the intended stream for each logical camera separately. Session-only endpoints/credentials are the default; explicit persistence uses macOS Keychain.

Check the **Choose / Name** box beside each saved camera and click **Use checked cameras**. The manager returns all selected camera configurations to the application's camera-wall controls without activating capture. Use the wall's explicit Start/Stop controls. Source-count and processing limits belong to the wall; being on the same network does not remove hardware throughput limits.

If a checked camera has expired session credentials, the whole selection is rejected with a useful message. Re-enter its address/credentials or uncheck it; the dialog does not silently start a partial selection. Single-source **Use camera** remains available. Camera probes and source selection are disabled while the parent reports active monitoring, preventing competing local captures.

## Executed validation

Evidence is under `docs/evidence/v021-2026-11-02/`:

- `network-tests.txt`: focused camera/network regressions, including interface validation/filtering, cancellation before socket creation, actual selected-interface UDP loopback, reply deduplication, interface-aware UI refresh, explicit checked selection and expired-credential rejection. Some component tests use identified fakes; they do not establish physical CCTV compatibility.
- `nearby-native-loopback.json`: native Cocoa interface with actual controlled UDP camera advertisements. Two camera services appeared, refresh deduplicated them, explicit batch selection returned two records and no capture started. Both screenshots contain only clearly labelled localhost fixtures.
- `nearby-real-lan.json`: actual current-network multicast completed in3.00seconds and received one camera-service advertisement. Names/endpoints are hashed in the report. No credentials or video were requested, so physical camera identity, authorization and video health are not verified by this discovery result.

`tools/verify_nearby_cctv_v021.py` reproduces the native controlled-advertiser check. `--lan` performs the bounded current-network discovery without signing in or opening frames. Its evidence scope distinguishes protocol/list behavior from physical video acceptance. The controlled native fixture uses real UDP transport but is explicitly not a physical CCTV.

## Integration API

`discover_cameras(timeout_s=3.0, cancel_event=None, interface_address=None)` preserves the existing return type and defaults. When an interface is supplied, multicast is bound to that local IPv4 address with link-local TTL1. `discovery_interfaces()` lists active nonloopback IPv4 interfaces from local OS metadata.

`CameraManagerDialog.camera_selected` keeps the existing single-selection contract. `cameras_selected` emits an object containing a tuple of resolved `CameraSelection` values after explicit **Use checked cameras**. Each selection carries the existing UUID, exact `SourceSpec` and session/Keychain-resolved credentials. The parent owns capture and schedules inference; the manager never starts it as a side effect of this signal.

References: [ONVIF discovery-mode API](https://www.onvif.org/yaml/wsdl-viewer2.php), [Apple local-network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy), [psutil local interface APIs](https://psutil.io/).
