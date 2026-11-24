"""H3MD face engine - written for H3MD, no other ComfyUI plugin needed.

  * ./lp  : LivePortrait network code, copied unchanged from Kuaishou's official repository
            (github.com/KlingTeam/LivePortrait, MIT, see lp/LICENSE).  The model weights are the official ones in
            safetensors form (Kijai/LivePortrait_safetensors), downloaded on first use to models/liveportrait.
  * ./yunet : OpenCV's YuNet face detector (MIT, see yunet/LICENSE), run with OpenCV's own FaceDetectorYN.
  * this file : model loading, face detection / square crop / paste-back, and the expression controls.
    The inference helpers in class Nets follow LivePortrait's official wrapper (MIT) in float32.
"""
from __future__ import annotations

import os
import threading
import urllib.request

import cv2
import numpy as np
import torch
import yaml

from .lp.camera import get_rotation_matrix, headpose_pred_to_degree
from .lp.modules.appearance_feature_extractor import AppearanceFeatureExtractor
from .lp.modules.motion_extractor import MotionExtractor
from .lp.modules.spade_generator import SPADEDecoder
from .lp.modules.stitching_retargeting_network import StitchingRetargetingNetwork
from .lp.modules.warping_network import WarpingNetwork

HERE = os.path.dirname(os.path.abspath(__file__))
TAG = "[H3MD Expression]"
WEIGHTS = ("appearance_feature_extractor", "motion_extractor", "warping_module", "spade_generator",
           "stitching_retargeting_module")
WEIGHT_URL = "https://huggingface.co/Kijai/LivePortrait_safetensors/resolve/main/{}.safetensors"
YUNET = os.path.join(HERE, "yunet", "face_detection_yunet_2023mar.onnx")
CROP_SIZE = 512                  # LivePortrait renders a 512 x 512 face
NET_INPUT = 256                  # ... from a 256 x 256 input

# YuNet's box is a little tighter and lower than the face box the expression presets were tuned with:
# measured on 5 portraits (2026-11-24), scale the side by 1.06 and lift the centre by 0.059 of it.
BOX_SCALE, BOX_DX, BOX_DY = 1.06, 0.006, -0.059


def _device():
    try:
        import comfy.model_management as mm
        return mm.get_torch_device()
    except Exception:
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _weights_dir():
    try:
        import folder_paths
        try:
            d = folder_paths.get_folder_paths("liveportrait")[0]
        except Exception:
            d = os.path.join(folder_paths.models_dir, "liveportrait")
    except Exception:
        d = os.path.join(HERE, "weights")
    os.makedirs(d, exist_ok=True)
    return d


def _fetch(url, path):
    print(f"{TAG} downloading {os.path.basename(path)} (LivePortrait weights, first use only) ...")
    tmp = path + ".part"
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    os.replace(tmp, path)


def _state_dict(name):
    """Weights for one network: the safetensors file in models/liveportrait (downloaded if missing), or the
    official .pth layout (base_models/, retargeting_models/) if a user already has that."""
    import comfy.utils
    d = _weights_dir()
    pth = os.path.join(d, "retargeting_models" if name == "stitching_retargeting_module" else "base_models", name + ".pth")
    if os.path.isfile(pth):
        sd = comfy.utils.load_torch_file(pth)
        if name == "stitching_retargeting_module":
            sd = {k.replace("module.", ""): v for k, v in sd["retarget_shoulder"].items()}
        return sd
    st = os.path.join(d, name + ".safetensors")
    if not os.path.isfile(st):
        try:
            _fetch(WEIGHT_URL.format(name), st)
        except Exception as e:
            raise RuntimeError(f"{TAG} could not download {name}.safetensors ({e}). Download it from "
                               f"{WEIGHT_URL.format(name)} and put it in {d}") from e
    sd = comfy.utils.load_torch_file(st)
    if name == "stitching_retargeting_module":
        sd = {k[len("retarget_shoulder_module."):]: v for k, v in sd.items() if k.startswith("retarget_shoulder_module.")}
    return sd


class Nets:
    """The five LivePortrait networks and the few steps H3MD uses (float32)."""

    def __init__(self):
        dev = _device()
        cfg = yaml.safe_load(open(os.path.join(HERE, "lp", "models.yaml"), "r"))["model_params"]
        build = {
            "appearance_feature_extractor": lambda: AppearanceFeatureExtractor(**cfg["appearance_feature_extractor_params"]),
            "motion_extractor": lambda: MotionExtractor(**cfg["motion_extractor_params"]),
            "warping_module": lambda: WarpingNetwork(**cfg["warping_module_params"]),
            "spade_generator": lambda: SPADEDecoder(**cfg["spade_generator_params"]),
            "stitching_retargeting_module": lambda: StitchingRetargetingNetwork(**cfg["stitching_retargeting_module_params"]["stitching"]),
        }
        self.m = {}
        for n in WEIGHTS:
            net = build[n]()
            net.load_state_dict(_state_dict(n))
            self.m[n] = net.to(dev).eval()
        self.device = dev

    @torch.no_grad()
    def get_kp_info(self, x):
        """x: 1x3x256x256 in 0..1 -> dict pitch/yaw/roll (degrees, Bx1), t, exp (Bx21x3), scale, kp (Bx21x3)."""
        info = self.m["motion_extractor"](x)
        bs = info["kp"].shape[0]
        for k in ("pitch", "yaw", "roll"):
            info[k] = headpose_pred_to_degree(info[k])[:, None]
        info["kp"] = info["kp"].reshape(bs, -1, 3)
        info["exp"] = info["exp"].reshape(bs, -1, 3)
        return info

    @torch.no_grad()
    def extract_feature_3d(self, x):
        return self.m["appearance_feature_extractor"](x).float()

    @staticmethod
    def transform_keypoint(info):
        """s * (kp @ R + exp) + t (t without z): the face's keypoints in the picture."""
        bs = info["kp"].shape[0]
        R = get_rotation_matrix(info["pitch"], info["yaw"], info["roll"])
        x = info["kp"].view(bs, -1, 3) @ R + info["exp"].view(bs, -1, 3)
        x = x * info["scale"][..., None]
        x[:, :, 0:2] += info["t"][:, None, 0:2]
        return x

    @torch.no_grad()
    def stitching(self, kp_source, kp_driving):
        """Small correction that keeps the edited face seamless with the rest of the crop."""
        bs, n = kp_source.shape[:2]
        delta = self.m["stitching_retargeting_module"](torch.cat([kp_source.view(bs, -1), kp_driving.view(bs, -1)], 1))
        out = kp_driving.clone()
        out += delta[..., :3 * n].reshape(bs, n, 3)
        out[..., :2] += delta[..., 3 * n:3 * n + 2].reshape(bs, 1, 2)
        return out

    @torch.no_grad()
    def warp_decode(self, feature_3d, kp_source, kp_driving):
        r = self.m["warping_module"](feature_3d, kp_source=kp_source, kp_driving=kp_driving)
        r["out"] = self.m["spade_generator"](feature=r["out"])
        return r

    @staticmethod
    def parse_output(out):
        a = np.transpose(out.data.cpu().numpy(), [0, 2, 3, 1])
        return (np.clip(a, 0, 1) * 255).astype(np.uint8)


class Prepared:
    """One source picture made ready for editing."""

    def __init__(self, src_rgb, crop_trans_m, x_s_info, f_s_user, x_s_user, mask_ori):
        self.src_rgb, self.crop_trans_m = src_rgb, crop_trans_m
        self.x_s_info, self.f_s_user, self.x_s_user, self.mask_ori = x_s_info, f_s_user, x_s_user, mask_ori


# ---------------------------------------------------------------------------- expression controls
# Each control moves some of LivePortrait's 21 implicit keypoints: (point, axis 0/1/2 = x/y/z, amount per unit).
# A few controls also turn the head a little so the move looks natural.  These are the controls the built-in
# expressions and the Studio sliders are written in.
_MOVES = {
    "smile": [(20, 1, -0.01), (14, 1, -0.02), (17, 1, 0.0065), (17, 2, 0.003),
              (13, 1, -0.00275), (16, 1, -0.00275), (3, 1, -0.0035), (7, 1, -0.0035)],
    "aaa": [(19, 1, 0.001), (19, 2, 0.0001), (17, 1, -0.0001)],                       # mouth open
    "eee": [(20, 2, -0.001), (20, 1, -0.001), (14, 1, -0.001)],                        # lips stretched
    "woo": [(14, 1, 0.001), (3, 1, -0.0005), (7, 1, -0.0005), (17, 2, -0.0005)],       # pucker
    "wink": [(11, 1, 0.001), (13, 1, -0.0003), (17, 0, 0.0003), (17, 1, 0.0003), (3, 1, -0.0003)],
    "pupil_y": [(11, 1, -0.001), (15, 1, -0.001)],
    "blink": [(11, 1, -0.001), (13, 1, 0.0003), (15, 1, -0.001), (16, 1, 0.0003), (1, 1, -0.00025), (2, 1, 0.00025)],
}
_MOVES_BY_SIGN = {                     # (when > 0, when < 0)
    "pupil_x": ([(11, 0, 0.0007), (15, 0, 0.001)], [(11, 0, 0.001), (15, 0, 0.0007)]),
    "eyebrow": ([(1, 1, 0.001), (2, 1, -0.001)], [(1, 0, -0.001), (2, 0, 0.001), (1, 1, 0.0003), (2, 1, -0.0003)]),
}
_HEAD_TURN = {"aaa": (-0.05, 0.0, 0.0), "wink": (0.0, -0.1, -0.1)}     # (pitch, yaw, roll) per unit


def expression_offsets(e, blink, eyebrow, wink, pupil_x, pupil_y, aaa, eee, woo, smile, pitch, yaw, roll):
    """Adds the controls' keypoint moves to e (1x21x3, in place) -> head turn tensor [pitch, yaw, roll] (degrees)."""
    v = {"smile": smile, "aaa": aaa, "eee": eee, "woo": woo, "wink": wink, "pupil_y": pupil_y,
         "blink": blink - pupil_y / 2.0,      # looking up opens the lids a little, looking down closes them
         "pupil_x": pupil_x, "eyebrow": eyebrow}
    for k, moves in _MOVES.items():
        if v[k]:
            for p, a, g in moves:
                e[0, p, a] += v[k] * g
    for k, (pos, neg) in _MOVES_BY_SIGN.items():
        for p, a, g in (pos if v[k] > 0 else neg):
            e[0, p, a] += v[k] * g
    head = [float(pitch), float(yaw), float(roll)]
    for k, turn in _HEAD_TURN.items():
        for i in range(3):
            head[i] += v[k] * turn[i]
    return torch.tensor(head)


# ---------------------------------------------------------------------------- the engine
class Engine:
    def __init__(self):
        self._nets = None
        self._det = None
        self._mask = None
        self._lock = threading.Lock()

    def nets(self):
        with self._lock:
            if self._nets is None:
                self._nets = Nets()
        return self._nets

    # ---- face finding
    def _detector(self):
        if self._det is None:
            self._det = cv2.FaceDetectorYN.create(YUNET, "", (320, 320), 0.7, 0.3, 50)
        return self._det

    def face_box(self, rgb):
        """Biggest face in the picture -> (cx, cy, side) in pixels, or None."""
        h, w = rgb.shape[:2]
        det = self._detector()
        det.setInputSize((w, h))
        _, faces = det.detect(cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2BGR))
        if faces is None or not len(faces):
            return None
        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])[:4]
        side = max(fw, fh)
        return x + fw / 2 + BOX_DX * side, y + fh / 2 + BOX_DY * side, side * BOX_SCALE

    def crop_square(self, rgb, crop_factor):
        """Square around the face, crop_factor x the face size, moved inside the picture where it fits
        -> [x1, y1, side] (may still reach past the edges of a tight picture; those parts are padded black)."""
        h, w = rgb.shape[:2]
        fb = self.face_box(rgb)
        if fb is None:
            print(f"{TAG} no face found - using the whole picture")
            side = max(w, h)
            return [int((w - side) / 2), int((h - side) / 2), int(side)]
        cx, cy, s = fb
        side = int(round(s * crop_factor))
        x1, y1 = int(round(cx - side / 2)), int(round(cy - side / 2))
        x1 = min(max(x1, 0), max(w - side, 0)) if side <= w else int(round((w - side) / 2))
        y1 = min(max(y1, 0), max(h - side, 0)) if side <= h else int(round((h - side) / 2))
        return [x1, y1, side]

    @staticmethod
    def cut(rgb, sq):
        """The square sq = [x1, y1, side] out of the picture (black outside it)."""
        x1, y1, side = sq
        h, w = rgb.shape[:2]
        pad = max(0, -x1, -y1, x1 + side - w, y1 + side - h)
        if pad:
            rgb = cv2.copyMakeBorder(rgb, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
            x1, y1 = x1 + pad, y1 + pad
        return rgb[y1:y1 + side, x1:x1 + side]

    def net_input(self, face):
        """Face crop (uint8 RGB) -> 1x3x256x256 tensor in 0..1 on the engine's device."""
        if face.shape[0] != NET_INPUT or face.shape[1] != NET_INPUT:
            face = cv2.resize(face, (NET_INPUT, NET_INPUT),
                              interpolation=cv2.INTER_AREA if face.shape[0] > NET_INPUT else cv2.INTER_LINEAR)
        x = torch.from_numpy(np.clip(face.astype(np.float32) / 255.0, 0, 1))[None].permute(0, 3, 1, 2)
        return x.to(self.nets().device)

    def read(self, rgb, sq):
        """LivePortrait's reading of the face inside square sq (expression, head angles ...)."""
        return self.nets().get_kp_info(self.net_input(self.cut(rgb, sq)))

    def _mask_template(self):
        if self._mask is None:
            self._mask = cv2.imread(os.path.join(HERE, "lp", "mask_template.png"), cv2.IMREAD_COLOR)
        return self._mask

    def prepare(self, rgb, crop_factor=1.7):
        """uint8 RGB picture -> Prepared (face found, cropped, read by LivePortrait)."""
        nets = self.nets()
        sq = self.crop_square(rgb, crop_factor)
        s = sq[2] / float(CROP_SIZE)
        crop_trans_m = np.float32([[s, 0, sq[0]], [0, s, sq[1]]])        # 512 crop -> picture
        mask = cv2.warpAffine(self._mask_template(), crop_trans_m, (rgb.shape[1], rgb.shape[0]), flags=cv2.INTER_LINEAR)
        x = self.net_input(self.cut(rgb, sq))
        info = nets.get_kp_info(x)
        return Prepared(rgb, crop_trans_m, info, nets.extract_feature_3d(x), nets.transform_keypoint(info),
                        mask.astype(np.float32) / 255.0)


ENGINE = Engine()
rotation_matrix = get_rotation_matrix
