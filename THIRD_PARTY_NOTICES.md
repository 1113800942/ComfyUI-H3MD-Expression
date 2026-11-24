# Third-party notices

H3MD Expression needs no other ComfyUI plugin. It contains or downloads the following:

| Part | Where | Source | License |
|---|---|---|---|
| LivePortrait network code (unchanged copy) | `face_engine/lp/` | Kuaishou, https://github.com/KlingTeam/LivePortrait (commit 9b294b3) | MIT, see `face_engine/lp/LICENSE` |
| LivePortrait model weights (not included; downloaded on first use to `models/liveportrait`) | — | official weights in safetensors form, https://huggingface.co/Kijai/LivePortrait_safetensors | MIT (LivePortrait) |
| YuNet face detector model | `face_engine/yunet/` | https://github.com/opencv/opencv_zoo | MIT, see `face_engine/yunet/LICENSE` |

`face_engine/engine.py` (model loading, face detection and cropping, paste-back, expression controls) and the rest of
this package are written for H3MD. The inference steps in `engine.py` follow LivePortrait's official wrapper (MIT).

Not used: InsightFace models (non-commercial license), YOLO / ultralytics face detection (AGPL).
