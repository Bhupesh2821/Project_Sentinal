# Earlier restricted-context measurements

**Superseded backend availability:** these first CPU measurements were collected inside the restricted execution context. Later approved native runs verified MPS and the desktop/camera. See `VERIFICATION_REPORT.md` and `docs/evidence/native/benchmark-native.json` for the final CPU/MPS comparison. The original bag misses below remain valid observations.

Measured on macOS-26.6.2-arm64-arm-64bit using Python 3.12.15, PyTorch 2.14.1, OpenCV 4.14.0, Ultralytics 8.4.183, and local YOLO11n weights. MPS was built into PyTorch but unavailable to the execution environment. All measurements in this earlier table ran on CPU. MPS was subsequently measured in the native context.

## Method

The real OpenCV sample is 768×576 at 10 FPS, with 795 source frames. The first 60 actual moving-video frames were processed independently at each inference size. Model loading is excluded; first-frame inference is retained in the raw data and excluded from the steady values below. The benchmark deliberately omits desktop playback waits to measure processing capacity. The desktop respects the file’s declared playback rate, so these numbers are not displayed playback FPS or a guaranteed live-camera rate. No concurrent model workload was run during this benchmark.

Image measurements use one warmup and 10 repeated local inferences per resolution. Confidence is 0.25, NMS IoU is 0.7, and ByteTrack receives detections down to 0.05 before presentation filtering. Source dimensions and output box coordinates are preserved. Raw measurements, individual detections, model/fixture SHA256 values and annotated images are retained in `docs/evidence/`.

## Real moving-video results

| Inference size | Steady pipeline FPS | Mean steady vision latency | Unique person IDs observed | Max simultaneous assigned IDs, all classes |
|---|---:|---:|---:|---:|
| 320 | 38.01 | 25.12 ms | 10 | 8 |
| 480 | 21.56 | 45.22 ms | 9 | 9 |
| 640 | 14.13 | 69.60 ms | 8 | 8 |

Repeated IDs were observed across adjacent real frames. The raw frame-index lists also show gaps in visible detections. At size 640, person ID 4 was absent between frames 17 and 35 (17 missing observations); person ID 15 had gaps of 6, 13 and 1 observations. These are recorded detection/track visibility interruptions, not verified identity switches. There are no identity ground-truth annotations for this clip, so IDF1, exact identity-switch counts and long-occlusion correctness were not measured. Distinct IDs over time do not equal a count of distinct physical people.

## Bag-category fixture results

Original COCO128 annotations were compared with the final warm image results using greedy, same-class IoU ≥ 0.5 matching. Each cell is matched annotations / total annotations. These three development images are from COCO train2017 and may overlap pretraining data. They do not estimate accuracy on unseen footage. “Unmatched predictions” below means not matched to this annotation file; it is not automatically a proven false positive.

| Inference size | Suitcase, image 260 | Backpack, image 328 | Handbag, image 315 |
|---|---:|---:|---:|
| 320 | 1/3 | 0/2 | 0/3 |
| 480 | 1/3 | 1/2 | 0/3 |
| 640 | 3/3 | 1/2 | 0/3 |

At 640, the suitcase fixture produced five suitcase predictions: three matched annotations and two were unmatched. The backpack fixture produced one matching backpack and missed the second annotated backpack. The handbag fixture produced no handbag prediction at any tested size and missed all three annotated handbags. Those misses remain in the raw evidence. Detection is scene-dependent; supporting a model class is not a promise to detect every instance.

The higher resolution improved suitcase matches on this sample and recovered a backpack absent at 320, while increasing CPU latency. This supports retaining 640 as the conservative default and offering lower sizes through configuration when responsiveness is more important. It does not establish a universal quality improvement for every scene.

Bag categories were tested on real still images; moving-bag identity continuity has not been independently demonstrated. V0.1 tracking claims rely on actual moving pedestrian footage and the generic supported-class tracking path. No unattended-baggage or owner-association behavior is implemented.

## Reproduction

```sh
.venv/bin/python tools/verify_pipeline.py --image tests/fixtures/000000000260.jpg --labels tests/fixtures/labels/000000000260.txt --video tests/fixtures/vtest.avi --frames 60 --repeats 10 --devices cpu mps --sizes 320 480 640 --output docs/evidence/benchmark-260-video.json
```

Run the image-only command for images `000000000328.jpg` and `000000000315.jpg`, supplying the matching label file and distinct output JSON. A missing MPS device is recorded as skipped, never as measured MPS performance. See `docs/FIXTURES.md` for input provenance.
