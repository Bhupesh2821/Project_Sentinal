# Using your own videos and live feeds

SENTINAL accepts a new video whenever you choose it. The application does not need a hard-coded filename or a restart when the source changes. Detection uses the same local YOLO model and tracker for imported files, the Mac camera and compatible network video feeds.

## Import any compatible local video

Click **Import & analyze video…**, choose your file, or drop one local video onto the dashboard. You can do this while another source is running. A background task copies and validates the file; its progress and **Cancel** control remain visible. The current source keeps running until the new video is ready. SENTINAL then releases that source, resets tracking for a new session and starts the imported video.

The **Imported video library** menu lets you analyze a previously imported video again. The selected filename, playback position, measured performance and real detections update from the active source. **Pause/Resume** stops or resumes file processing. The timeline can seek when the decoder reports a usable duration. Seeking starts fresh tracking identities rather than pretending IDs survived the jump. At EOF, **Replay video** opens a new session.

Uploads are managed local imports into `data/videos` inside Project Sentinal. The external original is left untouched. Duplicate content is reused instead of stored repeatedly. A missing, corrupt or unsupported file reports an error; no substitute footage or detections are generated. Codec support depends on the installed decoder, so “any video” means any file that this OpenCV build can actually decode. Video imports are kept until you remove them; the seven-day retention setting applies to optional detection metadata, not imported media. All import staging, indexes and temporary files stay in the project folder.

## Built-in or external Mac camera

Select **Camera**, choose the available device and press **Start monitoring**. No camera opens merely because the app launches or its device list refreshes. macOS may ask for camera access for the Python/launcher host. **Stop monitoring** releases the source. Camera frames are processed in memory; there is no microphone capture or automatic camera recording.

Live mode favors current frames. If capture is faster than inference, older queued frames are skipped instead of building a long backlog. The footer shows measured frame age and skipped-frame count. These measurements do not promise a fixed camera FPS. Lower **Inference size** when a feed is too slow; smaller inputs may miss distant bags or people.

## Network camera

Select **Network camera**, enter the camera's direct RTSP, RTSPS, HTTP or HTTPS video URL, fill the separate username/password fields if required, and press **Start monitoring**. Obtain the exact video URL from your camera configuration; a vendor's HTML login page is not a video stream. The app does not discover ONVIF endpoints or bypass authentication.

Credentials remain in memory and are not saved in the video library or settings. If you paste a URL containing user credentials, the app moves them into the separate fields and masks the password. Status messages use a safe host/port label. Changing to a different camera endpoint clears the previous endpoint's credentials. Feed loss has bounded reconnect attempts; fresh reconnections receive new tracking sessions. The dashboard clears stale object counts while reconnecting.

Network feeds necessarily receive video from the address you enter. AI processing remains on this Mac, and SENTINAL does not upload processed footage to an AI service. No remote connection is started before your explicit Start action. Stop ends the connection. The current prototype monitors one source at a time; importing another video safely switches away from that source.

## What the results mean

People, backpack, handbag and suitcase outputs are model observations. Real footage can contain missed objects, false detections, track loss and ID changes. An assigned ID estimates continuity within the current session; it does not identify a person or associate a bag with an owner. Import, decoder, UI and network-transport tests are separate from model accuracy and physical camera compatibility. Consult the current verification report for actual executed tests and remaining field checks.


### V0.1.2 camera and catalog update

Camera selection uses exact device identities. Stop, select the named Mac or iPhone camera and Start. A missing selected device cannot open another camera. Use Find / connect CCTV for user-initiated ONVIF discovery/profile selection, or enter an RTSP/HTTP stream directly. See CAMERA_NETWORK_SETUP.md. Choose the extended model while stopped and browse its searchable object catalog; safety/tool recognition remains subject to the misses and unsupported categories in VERIFICATION_REPORT.md. No person identity database is created.
