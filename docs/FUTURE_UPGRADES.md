# Connecting V0.2 BAGWATCH to Vision Core

Vision Core makes observations. V0.1 does not infer ownership, abandonment,
danger, intent, identity, violence, firearms, or incidents. The next module must
make those distinctions explicit and keep a human review step for alerts.

## Stable observation contract

`sentinal.vision.types.FramePacket` is the UI-independent observation delivered
once per processed source frame. It contains:

| Field | Meaning |
|---|---|
| `frame` | Original source image, BGR NumPy array. Treat it as read-only. |
| `detections` | Tuple of validated `Detection` records for this frame. |
| `session_id` | Unique UUID for this monitoring run. |
| `source` | Human-readable local camera or video source description. |
| `frame_index` | Source frame index within this run. |
| `timestamp` | UTC wall-clock observation time with timezone. |
| `source_time_s` | Video media position, or elapsed capture time for a camera. |
| `fps` | Measured processing throughput; not a fixed capability claim. |
| `inference_ms` | Measured latency of this frame's model/tracker operation. |
| `average_inference_ms` | Moving average of measured inference latency. |
| `device` | Actual execution backend, including fallback. |

Each `Detection` has `class_id`, `label`, `confidence`, `bbox=(x1,y1,x2,y2)`
in **original source pixels**, and optional `track_id`. Coordinates are finite,
nonnegative, and have positive area. An unassigned ID is `None`, not a reusable
sentinel identity. Supported bag labels are `backpack`, `handbag`, and `suitcase`.
Do not assume that every bag will be detected or that tracking never switches
identities.

An object key is `(session_id, track_id)`, never `track_id` alone. A new source,
restart, or new run resets tracker state and creates a new session. ByteTrack
IDs are associations within a session; they do not identify a person across
cameras or separate sessions.

## Integration point

Keep BAGWATCH in a new package such as `sentinal/events/bagwatch.py`, with a
bounded state machine receiving each packet from the pipeline consumer:

```python
packet = pipeline.step(confidence=0.25, focus_only=False)
if packet is not None:
    candidate_events = bagwatch.observe(packet)
```

The Qt application reads the newest packet from a one-frame worker mailbox; state changes use Qt signals. For
desktop integration, subscribe in the worker or use a separate event worker and
a bounded queue of observation metadata. Do not perform slow event analysis in
the GUI thread. A headless service can consume the same pipeline directly;
PySide6 is not required by the vision contracts or synchronous pipeline.

Use all relevant detections for analysis and apply presentation filters only at
the consumer boundary. Keep `observe()` deterministic with no UI dependencies.
Do not retain full frames unless the user separately enables that feature. The
V0.1 SQLite sampling interval is designed for lightweight development metadata;
it is too sparse to serve as the sole input for continuous dwell-time analysis.

## State needed by BAGWATCH

Maintain bounded per-session person and bag trajectories keyed by the composite
object key. Retain last position, timestamp, confidence, missing-frame duration,
and association uncertainty. Expire objects after a configured grace interval
and clear the complete state on a source/session change or backward media seek.

Measure file dwell times using `source_time_s`; use monotonic elapsed capture
time for live sessions. Wall-clock timestamps are appropriate for audit records,
but may jump when system time changes. A pause in processing or a lost source
must not silently accumulate confirmed abandonment time.

Person-bag proximity is only an association estimate. Introduce configurable
distance normalization, a sustained association period, an owner-separation
grace period, and an explicit uncertain state. Long occlusion, crowded scenes,
camera motion, or tracker ID switches require re-establishing the association.

## Event contract and storage

Add a separate event record with its own event UUID, session ID, object keys,
rule/configuration version, start/last-seen media times, status, evidence summary,
and uncertainty. Keep events distinct from V0.1 sampled detections. A future
database migration should add event and review tables without changing existing
detection semantics. An alert should be a reviewable rule candidate, not an
assertion of intent or guilt.

## Acceptance work before claiming V0.2

Test labelled real footage of carried bags, briefly placed bags, ordinary
occlusion, owner return, several nearby people, stationary luggage, source loss,
camera movement, and identity switches. Measure false alerts, missed events,
time-to-review, and association error. Include negative cases and define the
annotation protocol. Synthetic trajectories can test timing and state-machine
logic; they cannot establish real-world unattended-bag performance.

No V0.2 rules, owner associations, unattended-bag alerts, or incident claims are
implemented by the V0.1 module described here.

## V0.1.1 input additions

Consumers must handle new session UUIDs after a file seek or network reconnect, as well as source switches. Live capture returns the newest decoded frame; skipped capture indices are intentional and reported by `FramePacket.dropped_frames`. `frame_age_ms` measures local capture-read through completed analysis, excluding upstream camera buffering and GUI paint. Live frames may be downscaled to a maximum edge of 1920; coordinates refer to `packet.frame`. File sources keep their decoded dimensions. Never infer a continuous person/bag trajectory across a reset or assume every capture frame was analyzed.


### V0.1.2 model and camera boundaries

Mac/iPhone observations originate from an explicitly selected stable device ID; there is no automatic substitution on disappearance. Camera adapters remain isolated from file/network processing. The detector canonicalizes label spelling between COCO and Open Images; class_id remains native to the selected model. FramePacket.model_name and metadata session model_name identify that label space; older rows without provenance remain unknown. Model switches create a fresh session. BAGWATCH should depend on normalized person/backpack/handbag/suitcase labels and source/session boundaries, never assume class ID0 is always person. Safety/tool labels remain object observations: no compliance/intent/event decisions are implemented.
