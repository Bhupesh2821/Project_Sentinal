# Local object catalogs

Choose the model while monitoring is stopped. Everyday objects is YOLO11n with 80 COCO categories. The two optional Open Images choices are YOLOv8n (lightweight) and YOLOv8s (higher capacity), sharing a verified 601-class label mapping. SENTINAL permits 577 object categories after removing demographic/body-part and weapon outputs. Browse supported categories searches the exact permitted catalog offline. No database of people's names or faces exists.

The 16 safety/tool labels are axe, bicycle helmet, boot, drill, flashlight, glove, goggles, hammer, helmet, ladder, construction nail, personal flotation device, scissors, screwdriver, tool and wrench. These are generic pretrained labels. They are not all demonstrated successes, protective certifications or compliance checks. Actual sampled recognition was weak; consult VERIFICATION_REPORT.md for misses and the limited positive helmet/ladder examples. Vests and fire extinguishers are unsupported here.

All models use the same real Ultralytics/ByteTrack pipeline. Their numeric class IDs differ; normalized object labels and model filename must accompany observations. The model is loaded locally on Start and reused until an explicit model change. Downloads run only through installation tools; stored weights are checksum-checked. The two expanded models need no new Python dependencies or full dataset download.

Official model/dataset reference: https://docs.ultralytics.com/datasets/detect/open-images-v7/ . Licenses and checksum files are recorded in LICENSE_NOTES.md and models/.
