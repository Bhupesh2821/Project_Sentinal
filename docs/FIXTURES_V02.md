# V0.2 public fixture provenance and distribution

Prepared November 2, 2026. The portable distribution uses an explicit allowlist of 44 files in `data/v02-demo/DISTRIBUTION_MANIFEST.json`. Every allowed file has a SHA256; media also has source/license metadata. The runtime never downloads these fixtures. Files excluded from redistribution remain local for the documented testing scope. No private user video, camera screenshot or microphone recording belongs to this fixture set.

## Selected still-image screening

`data/v02-evaluation/labels.json` identifies17 scenes:14 natural public photos and 3 derived tests. Approximate boxes were annotated by one developer. Photos were selected during development; no training/test separation or representative field sampling is claimed. Exact per-file source metadata, original author/title/license details and hashes remain beside each photo.

| File | Author / source credit | License | Source / changes |
|---|---|---|---|
| `handgun.jpg` | US Army; color adjustment by Wikimedia user Hohum | Public domain US Army employee official duties | [Original source](https://commons.wikimedia.org/wiki/File:M1911a1.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `rifle.jpg` | Unknown author | Public domain | [Original source](https://commons.wikimedia.org/wiki/File:A_Marine_armed_with_an_M16_rifle_stands_guard_in_a_bunker_at_Beirut_International_Airport_DN-SN-84-05182.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `knife.jpg` | Jacek Halicki | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [Original source](https://commons.wikimedia.org/wiki/File:2020_No%C5%BCe_kuchenne_Gerlach.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `fire.jpg` | Forest Service Pacific Northwest Region | Public domain | [Original source](https://commons.wikimedia.org/wiki/File:Flames_in_Ochoco_Forest_July_25_-2026_Fire_Season_in_the_Forest_Service_Pacific_Northwest_Region.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `smoke.jpg` | Brocken Inaglory | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) | [Original source](https://commons.wikimedia.org/wiki/File:Wildfire_in_Yellowstone_National_Park_produces_Pyrocumulus_clouds1.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `campfire.jpg` | Marc-Lautenbacher | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [Original source](https://commons.wikimedia.org/wiki/File:Campfire_flames_at_night.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `hairdryer.jpg` | Dinkun Chen | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [Original source](https://commons.wikimedia.org/wiki/File:HITACHI_HAIR_DRYER_HD-1650.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `drill.jpg` | Matti Blume | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.en) | [Original source](https://commons.wikimedia.org/wiki/File:Panasonic_Cordless_Drill_%26_Driver_EY1DD2,_Ottobrunn_(20250410-P1046293).jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `steam.jpg` | Seasider53 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0) | [Original source](https://commons.wikimedia.org/wiki/File:Steaming_Tea_Kettle_2025.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `fog_photo.jpg` | W.carter | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [Original source](https://commons.wikimedia.org/wiki/File:Forested_hills_in_Lysekil_in_fog_-_B%26W.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `lamp.jpg` | Neil Owen | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0) | [Original source](https://commons.wikimedia.org/wiki/File:The_Three_Lamps_at_night_-_geograph.org.uk_-_7430314.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `reflection.jpg` | Basile Morin | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) | [Original source](https://commons.wikimedia.org/wiki/File:Water_reflection_of_sunset_with_gray_and_orange_clouds_and_boats_moored_to_the_bank_in_Pakse_Laos.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `dust.jpg` | Yathin S Krishnappa | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) | [Original source](https://commons.wikimedia.org/wiki/File:Dust_Cloud_in_Etosha_National_Park.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `bright_light.jpg` | Maxim Bilovitskiy | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0) | [Original source](https://commons.wikimedia.org/wiki/File:Maardu_Northern_lights_%E2%80%94_Estonia,_2022.jpg) — Downloaded public photo; stored source record identifies exact bytes. |
| `handgun_dark.jpg` | US Army; color adjustment by Wikimedia user Hohum | Public domain | [Original source](https://commons.wikimedia.org/wiki/File:M1911a1.jpg) — Derived: brightness multiplied .25 |
| `handgun_occluded.jpg` | US Army; color adjustment by Wikimedia user Hohum | Public domain | [Original source](https://commons.wikimedia.org/wiki/File:M1911a1.jpg) — Derived: synthetic gray vertical occlusion x230:380 |
| `screen_flames_derived.jpg` | Marc-Lautenbacher | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | [Original source](https://commons.wikimedia.org/wiki/File:Campfire_flames_at_night.jpg) — Derived: Original licensed fire photo rendered inside a synthetic display bezel; simulated screen confounder, not natural photograph |

CC BY/CC BY-SA images and adaptations retain those specific terms; their credits/source/license links are supplied above and in each sidecar. Derived screen rendering remains CC BY-SA 4.0. Public-domain marks describe the supplied government-source materials; SENTINAL does not claim authorship of them. Unidentified individual authors remain identified that way instead of inventing a credit.

The dark handgun multiplies brightness by0.25; the occluded handgun adds a synthetic gray strip; the screen confounder places the licensed campfire photo inside a synthetic display bezel. These are derived test scenes and are not described as independent natural low-light/occlusion/screen photographs. The bright-light example is an aurora photo, the lamp is a night street-lamp photo and the reflection is an orange sunset/water photo; the dataset does not establish broad coverage of each confounder class.

## Included demonstration videos

| File in `data/v02-demo` | Provenance / rights | Transformation and test scope |
|---|---|---|
| `handgun_repeated_still.mp4` | US Army M1911 photo; public domain, US Army / Wikimedia Hohum credit |8 seconds at 10 fps, video-only repeated real photo; no embedded predictions. |
| `fire_repeated_still.mp4` | Forest Service Pacific Northwest Region; public domain |8 seconds at 10 fps, repeated real photo resized to at most 1280 pixels wide; no embedded predictions. |
| `smoke_repeated_still.mp4` | Brocken Inaglory; [CC BY-SA3.0](https://creativecommons.org/licenses/by-sa/3.0/), [original](https://commons.wikimedia.org/wiki/File:Wildfire_in_Yellowstone_National_Park_produces_Pyrocumulus_clouds1.jpg) |8 seconds at 10 fps, repeated/resized photo; adaptation retains CC BY-SA3.0; no embedded predictions. |
| `weapon_range_motion.mp4` | Ramon Cardoza / U.S. Marine Corps; public-domain government video, [DVIDS source](https://www.dvidshub.net/video/967533/5th-anglico-pistol-range) | Genuine moving footage, original source 5–15 s, resized to 1280 pixels wide, audio removed. It shows an authorized qualification range, not an emergency or injury scenario. |

Repeated-still videos verify actual detector → temporal event → interface/review integration. Repetition does not establish natural-motion accuracy or tracker identity quality. The range derivative contains 300 frames at 29.97 fps (10.01 s); FFmpeg stream metadata confirmed one video stream and zero audio streams. Its original contains third-party licensed music, so only the silent derivative is allowed into the portable archive. No original music rights are claimed or redistributed. Each included clip has its own `.source.json` with exact SHA256, transformations and source credit.

## Local-only moving footage and excluded assets

`fireplace_motion.mp4` is a genuine 9.05 s / 217 frame stock fireplace clip from [Mixkit item 1242](https://mixkit.co/free-stock-video/wood-burning-in-a-fireplace-1242/), labelled Stock Video Free License by its source. `smoke_motion.mp4` is a genuine industrial-plume clip from [Mixkit item 1597](https://mixkit.co/free-stock-video/factory-smoke-1597/). The saved source/license pages document local evaluation use. Their raw stock files are excluded from the portable archive because standalone/raw redistribution scope is not established here. They are not claimed as SENTINAL-owned media. Obtain an appropriate copy directly from the publisher and review the [applicable Mixkit terms](https://mixkit.co/license/) to reproduce those tests.

The NPS fire original is excluded because the saved general-use page does not establish the exact clip rights. Unused downloaded thumbnails/photos and the untrimmed DVIDS original are excluded. Experimental model checkpoints and local RTSP test executables are also excluded by their separate package allowlists. Nothing was deleted or moved into an unrelated project.

## Evaluation evidence and limitations

- `docs/evidence/v02-2026-11-01/model-evaluation.json`: actual 640-input model observations, both 0.35 / 0.60 thresholds, same-class IoU 0.5 and separate scene-presence metrics. The320/480 comparison JSONs use the same 17 scenes.
- `model-benchmark.json`: actual12 warm calls per configuration, both specialized models + ByteTrack, CPU/MPS and320/480/640; excludes ordinary object inference, camera decoding and UI.
- `natural-motion-model-events.json`: real 0.2 s sampled moving-clip observations/events. Fireplace fire confirmation succeeded; range handgun observations did not satisfy 1 s persistence; industrial smoke had 72 samples and zero detections. False alerts are retained.
- Native desktop integration reports in the same evidence folder record exact source, detector provenance, rule settings and review/persistence behavior. Check their individual scope; repeated stills and natural movement are never counted interchangeably.

These legal test materials are suitable for a constrained prototype demonstration; they are not a safety certification, universal camera benchmark or unbiased accuracy dataset. Persistent lookalikes, misses, low detail, occlusion and source changes require further representative evaluation.
