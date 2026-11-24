"""H3MD Expression - core.

Edits the face of ONE reference picture into a micro-expression and returns a small frame group
(onset -> peak -> release) for H3MD keyframes / references.

Engine: H3MD's own face_engine package (LivePortrait networks from Kuaishou's official MIT code + our own face
detection, cropping and expression controls) - no other plugin needed.  What H3MD adds:
  * an expression wardrobe (presets/expressions.json): each expression has several styles ("cold smile" A/B/C ...),
    every style = the editor's sliders + optional raw keypoint offsets, and an English muscle-action line for prompts
  * left / right sides: a style may give the screen-left and screen-right half of the face different settings
    (one-sided smirk ...).  Both halves are rendered with the SAME head pose and blended across the face's middle
    (the two renders are pixel aligned, so the seam is invisible)
  * a frame group: onset (part strength) -> peak -> release (own release settings or part strength)
"""
from __future__ import annotations

import copy
import json
import os
import sys

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
PRESET_FILE = os.path.join(HERE, "presets", "expressions.json")
SLIDERS = ("pitch", "yaw", "roll", "blink", "eyebrow", "wink", "pupil_x", "pupil_y", "aaa", "eee", "woo", "smile")
HEAD = ("pitch", "yaw", "roll")
TAG = "[H3MD Expression]"


# ----------------------------------------------------------------------------- engine access
from .face_engine import engine as FE


# ----------------------------------------------------------------------------- presets
def load_presets(path=PRESET_FILE):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["expressions"]


def expression_names(presets=None):
    presets = presets or load_presets()
    return [f"{e['id']} | {e['zh']}" for e in presets] + [f"my/{n}" for n in library_names()]


def library_dir():
    """User expression library: <first models root>/h3md_expressions (next to refmods / liveportrait)."""
    try:
        import folder_paths
        try:
            base = os.path.dirname(os.path.normpath(folder_paths.get_folder_paths("refmods")[0]))
        except Exception:
            base = folder_paths.models_dir
    except Exception:
        base = HERE
    d = os.path.join(base, "h3md_expressions")
    os.makedirs(d, exist_ok=True)
    return d


def library_names():
    try:
        return sorted(os.path.splitext(f)[0] for f in os.listdir(library_dir()) if f.endswith(".json") and not f.startswith("_"))
    except Exception:
        return []


def safe_name(name):
    import re
    n = re.sub(r"[^A-Za-z0-9_\-]+", "_", (name or "").strip()).strip("_")
    if not n:
        raise ValueError(f"{TAG} give the expression a name (letters, digits, _ or -)")
    return n


def save_recipe(rec, overwrite=False):
    p = os.path.join(library_dir(), rec["name"] + ".json")
    if os.path.exists(p) and not overwrite:
        raise ValueError(f"{TAG} '{rec['name']}' already exists in the library - pick another name or turn overwrite on")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    return p


def load_recipe(choice):
    name = choice.split("/", 1)[1]
    with open(os.path.join(library_dir(), name + ".json"), "r", encoding="utf-8") as f:
        return json.load(f)


def find(presets, choice):
    key = choice.split("|")[0].strip()
    for e in presets:
        if e["id"] == key:
            return e
    raise ValueError(f"{TAG} unknown expression '{choice}'")


def _scaled(p, k):
    out = {s: float(p.get(s, 0.0)) * k for s in SLIDERS}
    out["kp"] = [[int(a), int(b), float(v) * k] for a, b, v in p.get("kp", [])]
    return out


def _add(a, b):
    out = {s: a.get(s, 0.0) + b.get(s, 0.0) for s in SLIDERS}
    out["kp"] = list(a.get("kp", [])) + list(b.get("kp", []))
    return out


def style_sides(style):
    """-> (screen_left_params, screen_right_params): 'both' + per-side additions."""
    both = style.get("both", {})
    left = _add(_scaled(both, 1.0), _scaled(style.get("left", {}), 1.0))
    right = _add(_scaled(both, 1.0), _scaled(style.get("right", {}), 1.0))
    return left, right


# ----------------------------------------------------------------------------- rendering
class FaceEditor:
    """One prepared source picture; render(left, right) -> full-size uint8 RGB."""

    def __init__(self, image_hwc_float, crop_factor=1.7):
        self.eng = FE.ENGINE
        self.rot = FE.rotation_matrix
        t = image_hwc_float[0] if image_hwc_float.dim() == 4 else image_hwc_float
        self.psi = self.eng.prepare((t.clamp(0, 1) * 255).byte().cpu().numpy(), crop_factor)
        self.pipe = self.eng.nets()

    def _motion(self, p):
        s = self.psi.x_s_info
        e = torch.zeros_like(s["exp"])
        r = FE.expression_offsets(e, p["blink"], p["eyebrow"], p["wink"], p["pupil_x"], p["pupil_y"], p["aaa"],
                                  p["eee"], p["woo"], p["smile"], p["pitch"], -p["yaw"], p["roll"])
        for k, a, v in p.get("kp", []):
            e[0, k, a] += v
        return e, r

    def _decode(self, e, r):
        s = self.psi.x_s_info
        s_exp = s["exp"].clone() + s["kp"]
        R = self.rot(s["pitch"] + r[0], s["yaw"] + r[1], s["roll"] + r[2])
        x = s["scale"] * ((s_exp + e) @ R) + s["t"]
        x = self.pipe.stitching(self.psi.x_s_user, x)
        out = self.pipe.warp_decode(self.psi.f_s_user, self.psi.x_s_user, x)
        return self.pipe.parse_output(out["out"])[0]          # 512x512 uint8 crop

    def render_crop(self, left, right):
        head = {h: left[h] for h in HEAD}                      # one head pose for both halves
        l = dict(left, **head); r_ = dict(right, **head)
        el, rot = self._motion(l)
        if _same(left, right):
            return self._decode(el, rot)
        er, _ = self._motion(r_)
        cl = self._decode(el, rot).astype(np.float32)
        cr = self._decode(er, rot).astype(np.float32)
        w = cl.shape[1]
        x = np.arange(w, dtype=np.float32)
        mid, feather = w * 0.5, w * 0.06
        m = np.clip((x - (mid - feather)) / (2 * feather), 0, 1)[None, :, None]   # 0 = screen left, 1 = right
        return np.clip(cl * (1 - m) + cr * m, 0, 255).astype(np.uint8)

    def paste(self, crop):
        import cv2
        psi = self.psi
        h, w = psi.src_rgb.shape[:2]
        full = cv2.warpAffine(crop, psi.crop_trans_m, (w, h), cv2.INTER_LINEAR)
        out = psi.mask_ori * full + (1 - psi.mask_ori) * psi.src_rgb
        return np.clip(out, 0, 255).astype(np.uint8)

    def render(self, left, right):
        return self.paste(self.render_crop(left, right))


    # ---- captured expressions (user library) ------------------------------------------------------------
    def render_crop_captured(self, e_abs=None, e_rel=None, rot_rel=(0.0, 0.0, 0.0), k=1.0, tune=None):
        """Captured expression on this face.  e_abs: an expression read from a photo (21x3, replaces this face's
        own expression by k); e_rel: a change measured inside a clip (added by k); rot_rel: head turn change
        (pitch, yaw, roll in degrees, added by k); tune = (left, right) slider fine-tuning on top (same both
        sides here; per-side tuning only for built-in styles)."""
        s = self.psi.x_s_info
        l = (tune or tune_params())[0]
        e, r = self._motion(l)
        if e_abs is not None:
            d = (torch.tensor(e_abs, dtype=e.dtype, device=e.device).view_as(e) - s["exp"])
            d[0, 5, 0:2] = 0          # point 5 x/y stays the face's own (keeps the face's own position)
            e = e + d * k
        if e_rel is not None:
            e = e + torch.tensor(e_rel, dtype=e.dtype, device=e.device).view_as(e) * k
        r = r + torch.tensor([float(x) * k for x in rot_rel], dtype=r.dtype)
        return self._decode(e, r)


def read_expressions(images, crop_factor=1.7):
    """IMAGE batch (one photo or the frames of a clip) -> [{'exp': 21x3 list, 'rot': [pitch, yaw, roll]}] per frame,
    read with the same LivePortrait motion extractor that renders the faces (identity is not stored: only the
    expression offsets and the head angles)."""
    eng = FE.ENGINE
    arr = (images.clamp(0, 1) * 255).byte().cpu().numpy()
    out = []
    sq = None
    for i, img in enumerate(arr):
        if sq is None:                                       # face found once on the first frame (clips: steady crop)
            sq = eng.crop_square(img, crop_factor)
        info = eng.read(img, sq)
        out.append({"exp": info["exp"][0].detach().cpu().float().tolist(),
                    "rot": [float(info["pitch"]), float(info["yaw"]), float(info["roll"])]})
    return out


def captured_recipe(name, frames_info, fps, label="", description="", head_motion=True):
    """-> recipe dict for the user library.  One frame = a photo (kind 'photo': the absolute expression; the clip is
    eased in and out like a built-in style).  Several frames = a clip (kind 'clip': every frame relative to the
    first one, resampled to 24 fps, so the clip's own timing is kept; the first frame should be calm)."""
    rec = {"format": "h3md-expression", "version": 1, "name": name, "label": label or name,
           "en": description or f"the facial expression '{label or name}'", "head_motion": bool(head_motion)}
    if len(frames_info) == 1:
        rec.update(kind="photo", exp=frames_info[0]["exp"])
        return rec
    n_src = len(frames_info)
    dur = n_src / float(fps)
    n24 = max(5, int(round(dur * 24)))
    n24 = 5 + 17 * max(0, int(round((n24 - 5) / 17.0)))     # H3 grid 17k+5
    e0 = np.array(frames_info[0]["exp"]); r0 = np.array(frames_info[0]["rot"])
    seq = []
    for j in range(n24):
        src = min(n_src - 1, int(round(j / max(1, n24 - 1) * (n_src - 1))))
        e = (np.array(frames_info[src]["exp"]) - e0).tolist()
        r = ((np.array(frames_info[src]["rot"]) - r0) if head_motion else np.zeros(3)).tolist()
        seq.append({"exp": e, "rot": r})
    while len(seq) < 22:                    # a very short clip: hold its last frame up to 22 f (~0.9 s) for H3
        seq.append(dict(seq[-1]))
    rec.update(kind="clip", frames=seq, fps=24)
    return rec


def captured_clip_params(rec):
    """-> [(e_abs, e_rel, rot_rel, k)] per output frame (24 fps)."""
    if rec["kind"] == "photo":
        out = []
        for phase, n in CLIP_PLAN:
            for i in range(n):
                t = _ease((i + 1) / n)
                k = {"still": 0.0, "rise": t, "hold": 1.0, "fall": 1.0 - 0.55 * t, "rest": 0.45}[phase]
                out.append((rec["exp"], None, (0, 0, 0), k))
        return out
    return [(None, f["exp"], f["rot"], 1.0) for f in rec["frames"]]


def _same(a, b):
    return all(abs(a[s] - b[s]) < 1e-6 for s in SLIDERS) and a.get("kp", []) == b.get("kp", [])


# ----------------------------------------------------------------------------- frame groups
def frame_params(style, strength, tune):
    """-> list of (name, left, right) for onset / peak / release."""
    left, right = style_sides(style)
    tl, tr = tune
    peak_l = _add(_scaled(left, strength), tl)
    peak_r = _add(_scaled(right, strength), tr)
    on = style.get("onset", 0.4)
    frames = [("onset", _scaled(peak_l, on), _scaled(peak_r, on)), ("peak", peak_l, peak_r)]
    rel = style.get("release")
    if isinstance(rel, dict):
        rl, rr = style_sides(rel)
        frames.append(("release", _add(_scaled(rl, strength), _scaled(tl, 0.5)),
                       _add(_scaled(rr, strength), _scaled(tr, 0.5))))
    else:
        k = float(rel) if rel is not None else 0.45
        frames.append(("release", _scaled(peak_l, k), _scaled(peak_r, k)))
    return frames


def _lerp(a, b, t):
    out = {s: a.get(s, 0.0) * (1 - t) + b.get(s, 0.0) * t for s in SLIDERS}
    # keypoint offsets: scale each side's list and concatenate (offsets add up)
    out["kp"] = [[k, ax, v * (1 - t)] for k, ax, v in a.get("kp", [])] + [[k, ax, v * t] for k, ax, v in b.get("kp", [])]
    return out


def _ease(t):
    return t * t * (3 - 2 * t)          # smoothstep: slow start, slow end (no jerk)


CLIP_PLAN = (("still", 4), ("rise", 10), ("hold", 9), ("fall", 12), ("rest", 4))   # 39 frames = 1.625 s at 24 fps


def clip_params(style, strength, tune):
    """-> [(left, right)] per frame of a continuous micro-expression clip (H3 grid 17k+5 = 39 frames):
    calm -> eased rise to the peak -> short hold -> eased fall to the release state -> rest."""
    zero = {s: 0.0 for s in SLIDERS}; zero["kp"] = []
    fr = frame_params(style, strength, tune)
    _, pl, pr = fr[1]
    _, rl, rr = fr[2]
    out = []
    for phase, n in CLIP_PLAN:
        for i in range(n):
            t = _ease((i + 1) / n)
            if phase == "still":
                out.append((zero, zero))
            elif phase == "rise":
                out.append((_lerp(zero, pl, t), _lerp(zero, pr, t)))
            elif phase == "hold":
                out.append((pl, pr))
            elif phase == "fall":
                out.append((_lerp(pl, rl, t), _lerp(pr, rr, t)))
            else:
                out.append((rl, rr))
    return out


def tune_params(eyebrow=0.0, eyes=0.0, smile=0.0, mouth_open=0.0, smile_left=0.0, smile_right=0.0,
                look_x=0.0, look_y=0.0, head_pitch=0.0, head_yaw=0.0, head_roll=0.0):
    """User fine-tuning on top of a style (eyes > 0 = more closed)."""
    base = {s: 0.0 for s in SLIDERS}
    base.update(eyebrow=eyebrow, blink=-eyes, smile=smile, aaa=mouth_open, pupil_x=look_x, pupil_y=look_y,
                pitch=head_pitch, yaw=head_yaw, roll=head_roll)
    base["kp"] = []
    l = dict(base, smile=smile + smile_left, kp=[])
    r = dict(base, smile=smile + smile_right, kp=[])
    return l, r
