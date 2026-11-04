# SENTINAL V0.2.1 — detection visibility and multiple-camera update

Preserves V0.2 camera/video/network adapters, local inference and human review. Fixes model predictions being hidden by ByteTrack confirmation, separates box display scores from temporal alert scores, and keeps each hazard overlay on its exact analyzed frame with a visible timestamp.

Adds an explicit Nearby CCTV list with local-interface selection, saved-camera batch selection and a bounded eight-source monitoring wall. Capture is independent per source; the ordinary and specialized models are shared by a fair serial scheduler. Per-camera observations, measured timings, warnings, individual Stop, shared incident history and human review are integrated. Latest incident intake is bounded per camera. Rapid restart waits for cleanup; failed capture cleanup prevents unsafe retry. Nothing starts from discovery or selection alone.

Adds an optional pinned official YOLO11s model and a reproducible real-model combination evaluation for the reported objects and existing positives/lookalikes. The original default and three model choices are preserved. Model quality remains experimental: some spoon/scissors/knife/fire examples still fail, a toy may produce a possible-weapon result, and loose-blade recognition has no dedicated independently validated detector. No setting eliminates all false positives/negatives.

Current measured verification, scope and unresolved defects are in VERIFICATION_REPORT.md. Prior release documents are retained in docs/verification/V0.2.0-* and the previous archive remains intact. No signed standalone app or Base44 website is claimed. All project-owned data remains in the existing canonical folder; privacy defaults remain off.
