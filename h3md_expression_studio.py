"""H3MD Expression Studio - live (what-you-see-is-what-you-get) expression workbench, backend part.

Pattern borrowed from AnyAngle Studio T8: a node button opens a full-screen editor in the browser; the heavy work
(face rendering with H3MD's own face_engine) runs here behind small HTTP routes; the finished state is stored as JSON
in the node's `studio` widget and turned into a RefMod when the node runs.

Studio state (JSON):
  {"version": 1,
   "base": {"kind": "none"}                                         sliders only
         | {"kind": "preset", "expression": "<id> | <zh>", "style": "A"}
         | {"kind": "my", "name": "<library name>"}                  a photo / clip entry of the user library
         | {"kind": "video", "frames": [{"exp": 21x3, "rot": [p,y,r]}...], "src": {...}}   a picked video segment
   "strength": 1.0, "tune": {<TUNE_KEYS>: float}, "head_motion": true, "label": "", "description": ""}
Fine-tuning rides the expression's own rise and fall (zero while the face is calm, full at the peak).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import threading

import numpy as np
import torch
from PIL import Image

from . import h3md_expression_core as X

# Fine-tuning controls, grouped by face part (head moves last).  Muscle controls are the parts of the engine's
# "smile" control split apart (mouth corners only / cheeks only) plus its lip shapes,
# each checked on a test face (2026-11-23).  No nose control: no LivePortrait point wrinkles the nose.
TUNE_GROUPS = [
    ("Brows 眉毛", [("brow_raise", "Raise 抬眉", 0, 15, 0.5), ("brow_knit", "Knit / frown 皱眉", 0, 15, 0.5)]),
    ("Eyes 眼睛", [("eyes_narrow", "Narrow (- wide) 眯眼(负=睁大)", -5, 20, 0.5), ("look_x", "Look left/right 眼看左右", -15, 15, 0.5),
                   ("look_y", "Look up/down 眼看上下", -15, 15, 0.5)]),
    ("Cheeks 脸颊", [("cheek_raise", "Raise cheeks 提脸颊", 0, 3, 0.05)]),
    ("Mouth 嘴巴", [("mouth_corners", "Corners up/down 嘴角上扬/下撇", -1.5, 1.5, 0.05),
                    ("mouth_corner_screen_left", "Corner, screen-left only 只动左边嘴角", -1.5, 1.5, 0.05),
                    ("mouth_corner_screen_right", "Corner, screen-right only 只动右边嘴角", -1.5, 1.5, 0.05),
                    ("lips_press", "Press lips 抿嘴", 0, 2, 0.05), ("lips_stretch", "Stretch lips 咧嘴", 0, 15, 0.5),
                    ("pucker", "Pucker 嘟嘴", 0, 15, 0.5), ("mouth_open", "Open 张嘴", -20, 80, 1),
                    ("smile", "Full smile (whole face) 整脸笑", -1, 1.3, 0.05)]),
    ("Head 头部", [("head_pitch", "Nod 点头", -15, 15, 0.5), ("head_yaw", "Turn 转头", -15, 15, 0.5),
                   ("head_roll", "Tilt 歪头", -15, 15, 0.5)]),
]
TUNE_KEYS = tuple(k for _, items in TUNE_GROUPS for k, *_ in items)
LEGACY_KEYS = ("eyebrow", "smile_screen_left", "smile_screen_right")
TUNE_RANGES = {"strength": (0.0, 2.0, 0.05)}
TUNE_RANGES.update({k: (lo, hi, st) for _, items in TUNE_GROUPS for k, _, lo, hi, st in items})
MAX_SEGMENT_S = 6.0          # a longer segment makes a heavy, slow RefMod: refuse instead of cutting it silently
CROP = 1.7
_LOCK = threading.Lock()


# ----------------------------------------------------------------------------- state -> frames
def _corner(v):
    return [[20, 1, -0.01 * v], [14, 1, -0.02 * v], [17, 1, 0.0065 * v], [17, 2, 0.003 * v]]


def _cheek(v):
    return [[13, 1, -0.00275 * v], [16, 1, -0.00275 * v], [3, 1, -0.0035 * v], [7, 1, -0.0035 * v]]


def _press(v):
    return [[19, 1, -0.006 * v], [20, 2, -0.012 * v]]


def tune_pair(tune):
    """tune dict -> (screen_left, screen_right) slider+keypoint params."""
    t = {k: float((tune or {}).get(k, 0.0)) for k in TUNE_KEYS + LEGACY_KEYS}
    base = {s: 0.0 for s in X.SLIDERS}
    base.update(eyebrow=t["brow_raise"] - t["brow_knit"] + t["eyebrow"], blink=-t["eyes_narrow"], smile=t["smile"],
                aaa=t["mouth_open"], eee=t["lips_stretch"], woo=t["pucker"], pupil_x=t["look_x"], pupil_y=t["look_y"],
                pitch=t["head_pitch"], yaw=t["head_yaw"], roll=t["head_roll"])
    shared = _cheek(t["cheek_raise"]) + _press(t["lips_press"])
    left = dict(base, smile=t["smile"] + t["smile_screen_left"],
                kp=shared + _corner(t["mouth_corners"] + t["mouth_corner_screen_left"]))
    right = dict(base, smile=t["smile"] + t["smile_screen_right"],
                 kp=shared + _corner(t["mouth_corners"] + t["mouth_corner_screen_right"]))
    return left, right


def _captured_plan(steps, tl, tr):
    """steps [(e_abs, e_rel, rot, k)] -> specs; fine-tuning scaled by the expression's envelope."""
    mag = []
    for ea, er, rr, k in steps:
        m = abs(k) * (np.abs(np.array(er)).sum() if er is not None else 1.0)
        mag.append(m)
    top = max(mag) if mag and max(mag) > 1e-9 else 1.0
    out = []
    for (ea, er, rr, k), m in zip(steps, mag):
        env = m / top
        out.append(("cap", ea, er, rr, k, X._scaled(tl, env), X._scaled(tr, env)))
    return out


def frame_plan(state):
    """-> list of render specs, one per output frame (24 fps)."""
    state = state or {}
    base = state.get("base") or {"kind": "none"}
    strength = float(state.get("strength", 1.0))
    tl, tr = tune_pair(state.get("tune"))
    kind = base.get("kind", "none")
    if kind == "preset":
        e = X.find(X.load_presets(), base["expression"])
        i = "ABCD".index(base.get("style", "A"))
        st = e["styles"][min(i, len(e["styles"]) - 1)]
        return [("lr", l, r) for l, r in X.clip_params(st, strength, (tl, tr))]
    if kind == "none":
        return [("lr", l, r) for l, r in X.clip_params({}, 1.0, (X._scaled(tl, strength), X._scaled(tr, strength)))]
    if kind == "my":
        rec = X.load_recipe("my/" + base["name"])
        if rec.get("kind") == "studio":
            return frame_plan(rec["state"])
        steps = [(ea, er, rr, k * strength) for ea, er, rr, k in X.captured_clip_params(rec)]
        return _captured_plan(steps, tl, tr)
    if kind == "video":
        hm = bool(state.get("head_motion", True))
        steps = [(None, f["exp"], f["rot"] if hm else [0.0, 0.0, 0.0], strength) for f in base["frames"]]
        return _captured_plan(steps, tl, tr)
    raise ValueError(f"{X.TAG} unknown studio source '{kind}'")


def peak_index(plan):
    best, bi = -1.0, 0
    for i, s in enumerate(plan):
        if s[0] == "lr":
            m = sum(abs(s[1].get(k, 0.0)) + abs(s[2].get(k, 0.0)) for k in X.SLIDERS) + \
                sum(abs(v) for _, _, v in s[1].get("kp", []))
        else:
            m = abs(s[4]) * (np.abs(np.array(s[2])).sum() if s[2] is not None else 1.0) + \
                sum(abs(s[5].get(k, 0.0)) for k in X.SLIDERS)
        if m > best:
            best, bi = m, i
    return bi


def render_spec(ed, spec):
    if spec[0] == "lr":
        return ed.render_crop(spec[1], spec[2])
    _, ea, er, rr, k, tl, tr = spec
    return ed.render_crop_captured(ea, er, rr, k, (tl, tr))


def render_clip(ed, state):
    with torch.inference_mode():
        return [render_spec(ed, s) for s in frame_plan(state)]


def state_hint(state):
    base = (state or {}).get("base") or {}
    if state.get("description"):
        return state["description"]
    if base.get("kind") == "preset":
        e = X.find(X.load_presets(), base["expression"])
        return f"{e['en']} ({e['zh']})"
    if base.get("kind") == "my":
        try:
            rec = X.load_recipe("my/" + base["name"])
            return rec.get("en", "")
        except Exception:
            return ""
    return state.get("label") or "a subtle facial expression"


def state_key(state):
    s = dict(state or {})
    for k in ("label", "description", "saved_name"):
        s.pop(k, None)
    return hashlib.sha1(json.dumps(s, sort_keys=True).encode()).hexdigest()[:8]


# ----------------------------------------------------------------------------- faces (cached editors)
_EDITORS = {}


def editor_for_file(path):
    st = os.stat(path)
    key = (os.path.normcase(path), st.st_mtime, st.st_size)
    if key not in _EDITORS:
        _EDITORS.clear()
        img = np.array(Image.open(path).convert("RGB")).astype(np.float32) / 255.0
        with torch.inference_mode():
            _EDITORS[key] = X.FaceEditor(torch.from_numpy(img), CROP)
    return _EDITORS[key]


# ----------------------------------------------------------------------------- videos
_VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v", ".gif")


class _Video:
    def __init__(self, path):
        import cv2
        self.path = path
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise ValueError(f"{X.TAG} cannot open video {path}")
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS)) or 24.0
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)); self.h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.pos = -1
        self.regions = {}          # reference frame index -> face square [x1, y1, side]
        self.info_cache = {}       # frame index -> {'exp', 'rot'}

    def frame(self, i):
        import cv2
        i = int(max(0, min(self.count - 1, i)))
        if i != self.pos + 1:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, bgr = self.cap.read()
        if not ok:
            raise ValueError(f"{X.TAG} cannot read frame {i}")
        self.pos = i
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    def region(self, ref_i):
        if ref_i not in self.regions:
            self.regions[ref_i] = X.FE.ENGINE.crop_square(self.frame(ref_i), CROP)
        return self.regions[ref_i]

    def read(self, i, ref_i):
        key = (i, ref_i)
        if key not in self.info_cache:
            info = X.FE.ENGINE.read(self.frame(i), self.region(ref_i))
            self.info_cache[key] = {"exp": info["exp"][0].detach().cpu().float().numpy(),
                                    "rot": np.array([float(info["pitch"]), float(info["yaw"]), float(info["roll"])])}
            if len(self.info_cache) > 4000:
                self.info_cache.clear()
        return self.info_cache[key]


_VIDEOS = {}


def video(path):
    st = os.stat(path)
    key = (os.path.normcase(path), st.st_mtime)
    if key not in _VIDEOS:
        _VIDEOS.clear()
        _VIDEOS[key] = _Video(path)
    return _VIDEOS[key]


FACE_MIN = 0.12        # face width / shorter frame side below this = too small to read fine detail
YAW_MAX, PITCH_MAX = 25.0, 20.0


def footage_warning(v, idx):
    """-> "" or a warning when the face is small or turned away in these frames (the read gets distorted)."""
    face = v.region(idx[0])[2] / CROP          # square side = face size x CROP
    en, zh = [], []
    if face / max(1, min(v.w, v.h)) < FACE_MIN:
        en.append("the face is small in the frame (use a close-up)"); zh.append("脸在画面里太小（请用近景）")
    yaw = max(abs(float(v.read(i, idx[0])["rot"][1])) for i in idx)
    pitch = max(abs(float(v.read(i, idx[0])["rot"][0])) for i in idx)
    if yaw > YAW_MAX or pitch > PITCH_MAX:
        en.append(f"the head turns away (up to {yaw:.0f} deg sideways, {pitch:.0f} deg up/down; keep it near front-facing)")
        zh.append(f"头转得太多（侧向最多 {yaw:.0f} 度，上下最多 {pitch:.0f} 度），请选接近正脸的片段")
    if not en:
        return ""
    return {"en": "This segment may not read well: " + "; ".join(en) + ".", "zh": "这段可能取不好：" + "；".join(zh) + "。"}


def capture_segment(path, start_s, end_s, head_motion=True):
    """Frames of [start, end] resampled to 24 fps on the H3 grid (17k+5), each relative to the start frame."""
    v = video(path)
    dur = float(end_s) - float(start_s)
    if dur <= 0:
        raise ValueError(f"{X.TAG} the end must be after the start")
    if dur > MAX_SEGMENT_S:
        raise ValueError(f"{X.TAG} the segment is {dur:.1f} s; keep it to {MAX_SEGMENT_S:.0f} s or less "
                         "(a longer one makes a heavy, slow RefMod)")
    n = max(5, int(round(dur * 24)))
    n = 5 + 17 * max(0, int(round((n - 5) / 17.0)))
    i0 = int(round(start_s * v.fps))
    i1 = int(round(end_s * v.fps))
    ref = v.read(i0, i0)
    frames = []
    with torch.inference_mode():
        for j in range(n):
            src = int(round(i0 + (i1 - i0) * j / max(1, n - 1)))
            inf = v.read(src, i0)
            rot = (inf["rot"] - ref["rot"]) if head_motion else np.zeros(3)
            frames.append({"exp": (inf["exp"] - ref["exp"]).tolist(), "rot": rot.tolist()})
        idx = [int(round(i0 + (i1 - i0) * j / max(1, n - 1))) for j in range(n)]
        warning = footage_warning(v, idx)
    return frames, warning


# ----------------------------------------------------------------------------- translation (local, small LLM)
# Only used when a description is written in Chinese.  Any Qwen3-VL text-encoder file ComfyUI can load works;
# the first one found in models/text_encoders (or models/clip) is used, a 4B one preferred.
_TR = {}


def _translator_path():
    import folder_paths
    found = []
    for kind in ("text_encoders", "clip"):
        try:
            names = folder_paths.get_filename_list(kind)
        except Exception:
            names = []
        for n in names:
            low = n.lower().replace("-", "").replace("_", "")
            if "qwen3vl" in low:
                found.append((0 if "4b" in low else 1, folder_paths.get_full_path(kind, n)))
    return sorted(found)[0][1] if found else None


def _translator():
    if "clip" not in _TR:
        import comfy.sd
        path = _translator_path()
        if not path:
            raise ValueError(f"{X.TAG} to write the description in Chinese, put a Qwen3-VL text encoder (4B is enough) "
                             "in models/text_encoders - or write the description in English, which needs no model")
        _TR["clip"] = comfy.sd.load_clip(ckpt_paths=[path], clip_type=comfy.sd.CLIPType.STABLE_DIFFUSION)
    return _TR["clip"]


def translate(text, to="en"):
    """Same calling path as ComfyUI's core Generate Text node (tokenize -> generate -> decode), greedy."""
    _no_prompt_guard()
    clip = _translator()
    if to == "en":
        sys_p = ("You translate short Chinese descriptions of a facial expression into one natural English phrase for a "
                 "video-generation prompt. Keep every detail (which brow, eye, cheek, mouth corner, which side). "
                 "Output only the English phrase, no quotes, no explanation.")
    else:
        sys_p = "Translate the text into simple Chinese. Output only the Chinese, no quotes, no explanation."
    tokens = clip.tokenize(text.strip(), min_length=1, thinking=False, system_prompt=sys_p)
    ids = clip.generate(tokens, do_sample=False, max_length=160, temperature=1.0, top_k=50, top_p=1.0, min_p=0.0,
                        repetition_penalty=1.0, presence_penalty=0.0, seed=None, mtp=False)
    out = clip.decode(ids)
    out = out.split("</think>")[-1].replace("<think>", "").strip().strip('"').strip()
    return out


# ----------------------------------------------------------------------------- character save -> RefMod
VAE_NAME = "minimax_h3_video_vae_fp16.safetensors"
_VAE = {}
FACE_DIR = "H3MD_expression_faces"
_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def _no_prompt_guard():
    try:     # node code may report progress to the running prompt; outside a prompt there is none yet
        from server import PromptServer
        if not hasattr(PromptServer.instance, "last_prompt_id"):
            PromptServer.instance.last_prompt_id = None
    except Exception:
        pass


def video_vae():
    if "vae" not in _VAE:
        import comfy.sd
        import comfy.utils
        import folder_paths
        path = folder_paths.get_full_path("vae", VAE_NAME)
        if not path:
            raise ValueError(f"{X.TAG} {VAE_NAME} not found in models/vae (needed to make a RefMod)")
        sd, meta = comfy.utils.load_torch_file(path, return_metadata=True)
        _VAE["vae"] = comfy.sd.VAE(sd=sd, metadata=meta)
    return _VAE["vae"]


def keep_face(image_spec):
    """Copy the picked picture into input/H3MD_expression_faces/<sha8>.<ext> so the saved character keeps
    working when the original is edited or deleted.  -> image spec of the copy."""
    import shutil
    import folder_paths
    src = _input_path(image_spec)
    with open(src, "rb") as f:
        h = hashlib.sha1(f.read()).hexdigest()[:10]
    ext = os.path.splitext(src)[1].lower() or ".png"
    d = os.path.join(folder_paths.get_input_directory(), FACE_DIR)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, h + ext)
    if not os.path.exists(dst):
        shutil.copyfile(src, dst)
    return {"filename": h + ext, "subfolder": FACE_DIR, "type": "input"}


def refmod_name(state):
    saved = (state or {}).get("saved_name")
    return X.safe_name(("my_" + saved) if saved else ("studio_" + state_key({k: v for k, v in state.items()
                                                                              if k not in ("image", "character")})))


def make_character_refmod(state, ref_resolution=512, vae=None, name=None):
    """Character picture (state.image) + expression -> RefMod models/refmods/expression/<character>/<name>.
    Made fresh every time (the user asked for it).  -> (loader name, file path, hint, clip uint8 list)."""
    from . import h3md_expression_nodes as N
    char = X.safe_name(state.get("character", ""))
    if not state.get("image"):
        raise ValueError(f"{X.TAG} load the character's picture first (Load Image)")
    name = X.safe_name(name) if name else refmod_name(state)
    if ref_resolution != 512:
        name += f"_r{ref_resolution}"
    sub = f"{N.SUBFOLDER}/{char}"
    hint = state_hint(state)
    ed = editor_for_file(_input_path(state["image"]))
    clip = render_clip(ed, state)
    _no_prompt_guard()
    N.encode_refmod(N._to_tensor(clip), vae or video_vae(), sub, name, hint, ref_resolution)
    path = os.path.join(N._refmods_root(), N.SUBFOLDER, char, name + ".safetensors")
    return f"{sub}/{name}", path, hint, clip


# ----------------------------------------------------------------------------- library gallery / whole set
# Built-in expressions are never edited in place: the user's renames and deletions live in the library folder,
# so a package update keeps them.
def _overrides_file():
    # leading "_": safe_name() never makes such a name, and library_names() skips it, so it is never listed as an expression
    return os.path.join(X.library_dir(), "_builtin_overrides.json")


def builtin_overrides():
    try:
        with open(_overrides_file(), "r", encoding="utf-8") as f:
            o = json.load(f)
    except Exception:
        o = {}
    return {"hidden": list(o.get("hidden", [])), "names": dict(o.get("names", {}))}


def _save_overrides(o):
    with open(_overrides_file(), "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=1)


def library_items():
    """Every expression in the library: built-in styles and my/ entries, each with its RefMod file name."""
    out = []
    ov = builtin_overrides()
    for e in X.load_presets():
        for i, st in enumerate(e["styles"]):
            style = "ABCD"[i]
            key = f"{e['id']}_{style}"
            if key in ov["hidden"]:
                continue
            out.append({"key": f"{e['id']}_{style}", "cat": "builtin", "title": f"{e['zh']} {st['name']}",
                        "title_en": f"{e['en'].capitalize()} {style}",
                        "sub": f"{e['en']} · {style}", "base": {"kind": "preset", "expression": f"{e['id']} | {e['zh']}",
                                                               "style": style}, "refmod": f"{e['id']}_{style}"})
            if key in ov["names"]:
                out[-1]["title"] = out[-1]["title_en"] = ov["names"][key]
    for nme in X.library_names():
        try:
            rec = X.load_recipe("my/" + nme)
        except Exception:
            continue
        out.append({"key": "my_" + nme, "cat": "mine", "title": rec.get("label") or nme, "title_en": rec.get("label") or nme,
                    "sub": f"my/{nme}",
                    "base": {"kind": "my", "name": nme}, "studio": rec.get("kind") == "studio", "refmod": "my_" + nme})
    return out


_THUMBS = {}
DEFAULT_FACE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets", "default_face.png")
BUILTIN_THUMBS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets", "thumbs")


def _thumb_file(item):
    if item["cat"] == "builtin":
        return os.path.join(BUILTIN_THUMBS, item["key"] + ".jpg")
    return os.path.join(X.library_dir(), "thumbs", item["base"]["name"] + ".jpg")


def default_thumbnail(item):
    """Thumbnail on the default face, kept as a file so opening the library needs no rendering.  Made once per
    expression (and again when a my/ entry was saved again)."""
    f = _thumb_file(item)
    stale = not os.path.exists(f) or (item["cat"] == "mine" and _lib_mtime(item) > os.path.getmtime(f))
    if stale:
        ed = editor_for_file(DEFAULT_FACE)
        plan = frame_plan({"base": item["base"], "strength": 1.0, "tune": {}})
        with torch.inference_mode():
            img = render_spec(ed, plan[peak_index(plan)])
        os.makedirs(os.path.dirname(f), exist_ok=True)
        im = Image.fromarray(img)
        im.thumbnail((256, 256))
        im.save(f, "JPEG", quality=86)
    with open(f, "rb") as fh:
        return "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode()


def delete_expression(name):
    """Remove a my/ expression (the recipe and its thumbnail only; RefMods already made stay where they are)."""
    nme = X.safe_name(name)
    p = os.path.join(X.library_dir(), nme + ".json")
    if not os.path.exists(p):
        raise ValueError(f"{X.TAG} my/{nme} is not in your library")
    os.remove(p)
    t = os.path.join(X.library_dir(), "thumbs", nme + ".jpg")
    if os.path.exists(t):
        os.remove(t)
    return nme


def hide_builtin(key):
    o = builtin_overrides()
    if key not in o["hidden"]:
        o["hidden"].append(key)
    _save_overrides(o)
    return key


def restore_builtins():
    o = builtin_overrides()
    n = len(o["hidden"])
    o["hidden"] = []
    _save_overrides(o)
    return n


def rename_expression(label, key=None, name=None):
    """Display name only: RefMod files and the my/ file name stay as they are, so nothing already made breaks."""
    label = (label or "").strip()
    if not label:
        raise ValueError(f"{X.TAG} type a name")
    if name:
        nme = X.safe_name(name)
        p = os.path.join(X.library_dir(), nme + ".json")
        with open(p, "r", encoding="utf-8") as f:
            rec = json.load(f)
        rec["label"] = label
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        return label
    o = builtin_overrides()
    o["names"][key] = label
    _save_overrides(o)
    return label


def thumbnail(image_spec, item):
    p = _input_path(image_spec)
    key = (os.path.normcase(p), os.stat(p).st_mtime, item["key"], _lib_mtime(item))
    if key not in _THUMBS:
        if len(_THUMBS) > 600:
            _THUMBS.clear()
        ed = editor_for_file(p)
        plan = frame_plan({"base": item["base"], "strength": 1.0, "tune": {}})
        with torch.inference_mode():
            _THUMBS[key] = jpeg_b64(render_spec(ed, plan[peak_index(plan)]), 256, 84)
    return _THUMBS[key]


def _lib_mtime(item):
    if item["cat"] != "mine":
        return 0
    try:
        return os.path.getmtime(os.path.join(X.library_dir(), item["base"]["name"] + ".json"))
    except OSError:
        return 0


def make_whole_set(image_spec, character):
    """The character's RefMod for every library expression; files that already exist are skipped."""
    from . import h3md_expression_nodes as N
    char = X.safe_name(character)
    img = keep_face(image_spec)
    folder = os.path.join(N._refmods_root(), N.SUBFOLDER, char)
    made, skipped, failed = [], [], []
    vae = video_vae()
    for it in library_items():
        if os.path.exists(os.path.join(folder, it["refmod"] + ".safetensors")):
            skipped.append(it["refmod"])
            continue
        try:
            make_character_refmod({"base": it["base"], "strength": 1.0, "tune": {}, "image": img, "character": char},
                                  vae=vae, name=it["refmod"])
            made.append(it["refmod"])
        except Exception as e:
            failed.append(f"{it['refmod']}: {e}")
    return {"made": made, "skipped": skipped, "failed": failed, "folder": folder, "image": img}


# ----------------------------------------------------------------------------- images out
def jpeg_b64(arr, max_side=None, q=88):
    im = Image.fromarray(arr)
    if max_side and max(im.size) > max_side:
        s = max_side / max(im.size)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.BILINEAR)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


# ----------------------------------------------------------------------------- routes
def _input_path(spec):
    import folder_paths
    name = spec.get("filename") if isinstance(spec, dict) else spec
    if not name:
        raise ValueError(f"{X.TAG} no picture loaded - pick one at the top (Load Image)")
    sub = spec.get("subfolder", "") if isinstance(spec, dict) else ""
    typ = spec.get("type", "input") if isinstance(spec, dict) else "input"
    base = {"input": folder_paths.get_input_directory(), "output": folder_paths.get_output_directory(),
            "temp": folder_paths.get_temp_directory()}.get(typ, folder_paths.get_input_directory())
    p = os.path.normpath(os.path.join(base, sub or "", name))
    if not p.startswith(os.path.normpath(base)):
        raise ValueError("bad path")
    if not os.path.exists(p):
        raise ValueError(f"{X.TAG} file not found: {name}")
    return p


def register_routes():
    try:
        from server import PromptServer
        from aiohttp import web
    except Exception:
        return
    routes = PromptServer.instance.routes
    import asyncio

    async def run(fn, *a):
        loop = asyncio.get_running_loop()

        def locked():
            with _LOCK:
                return fn(*a)
        return await loop.run_in_executor(None, locked)

    def ok(d):
        return web.json_response(d)

    def err(e):
        import traceback
        print(f"{X.TAG} studio route error:\n" + traceback.format_exc())
        return web.json_response({"error": str(e)}, status=400)

    @routes.get("/h3md_expression/studio/meta")
    async def meta(request):
        try:
            import folder_paths
            vids, imgs = [], []
            root = folder_paths.get_input_directory()
            for dp, _, fs in os.walk(root):
                for f in fs:
                    rel = os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")
                    if f.lower().endswith(_VIDEO_EXT):
                        vids.append(rel)
                    elif f.lower().endswith(_IMG_EXT) and not rel.startswith(FACE_DIR + "/"):
                        imgs.append(rel)
            presets = [{"value": f"{e['id']} | {e['zh']}", "en": e["en"], "zh": e["zh"],
                        "styles": [s["name"] for s in e["styles"]]} for e in X.load_presets()]
            lib = []
            for n in X.library_names():
                try:
                    r = X.load_recipe("my/" + n)
                    lib.append({"name": n, "label": r.get("label", n), "kind": r.get("kind", "")})
                except Exception:
                    pass
            return ok({"presets": presets, "library": lib, "videos": sorted(vids), "tune": TUNE_RANGES, "groups": TUNE_GROUPS, "images": sorted(imgs),
                       "max_segment": MAX_SEGMENT_S})
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/face")
    async def face(request):
        try:
            d = await request.json()
            p = _input_path(d["image"])
            await run(editor_for_file, p)
            return ok({"ok": True})
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/render")
    async def render(request):
        try:
            d = await request.json()
            p = _input_path(d["image"])

            def job():
                ed = editor_for_file(p)
                plan = frame_plan(d.get("state"))
                pk = peak_index(plan)
                i = pk if d.get("frame") in (None, "peak") else int(max(0, min(len(plan) - 1, int(d["frame"]))))
                with torch.inference_mode():
                    img = render_spec(ed, plan[i])
                return {"image": jpeg_b64(img), "frames": len(plan), "peak": pk, "frame": i}
            return ok(await run(job))
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/export_image")
    async def export_image(request):
        """The frame the timeline is on -> output/ as PNG: the whole picture at full size with the new expression,
        or with face_only the face crop (512 x 512).  A plain image for keyframes or any image edit, no H3 needed."""
        try:
            d = await request.json()
            p = _input_path(d["image"])

            def job():
                import folder_paths
                ed = editor_for_file(p)
                plan = frame_plan(d.get("state"))
                i = peak_index(plan) if d.get("frame") in (None, "peak") else int(max(0, min(len(plan) - 1, int(d["frame"]))))
                with torch.inference_mode():
                    crop = render_spec(ed, plan[i])
                full = crop if d.get("face_only") else ed.paste(crop)
                out_dir = folder_paths.get_output_directory()
                try:
                    stem = "H3MD_expr_" + X.safe_name(d.get("name") or "")
                except ValueError:
                    stem = "H3MD_expr"
                n = 1
                while os.path.exists(os.path.join(out_dir, f"{stem}_{n:05d}.png")):
                    n += 1
                fn = f"{stem}_{n:05d}.png"
                Image.fromarray(full).save(os.path.join(out_dir, fn))
                return {"filename": fn, "folder": out_dir, "frame": i, "size": [int(full.shape[1]), int(full.shape[0])]}
            return ok(await run(job))
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/clip")
    async def clip(request):
        try:
            d = await request.json()
            p = _input_path(d["image"])

            def job():
                clip_ = render_clip(editor_for_file(p), d.get("state"))
                return {"frames": [jpeg_b64(c, 384, 82) for c in clip_], "fps": 24}
            return ok(await run(job))
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/video/info")
    async def vinfo(request):
        try:
            d = await request.json()
            p = _input_path(d["video"])
            v = await run(video, p)
            return ok({"fps": v.fps, "count": v.count, "duration": v.count / v.fps, "w": v.w, "h": v.h})
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/video/frame")
    async def vframe(request):
        """Source frame at t + the character's face doing that frame's expression (relative to the start mark)."""
        try:
            d = await request.json()
            vp = _input_path(d["video"])
            ip = _input_path(d["image"]) if d.get("image") else None

            def job():
                v = video(vp)
                i = int(round(float(d.get("t", 0)) * v.fps))
                ref = int(round(float(d.get("ref_t", 0)) * v.fps))
                out = {"source": jpeg_b64(v.frame(i), 480, 80)}
                if ip:
                    ed = editor_for_file(ip)
                    try:
                        with torch.inference_mode():
                            a, b = v.read(i, ref), v.read(ref, ref)
                            rot = (a["rot"] - b["rot"]) if d.get("head_motion", True) else np.zeros(3)
                            st = d.get("state") or {}
                            tl, tr = tune_pair(st.get("tune"))
                            img = ed.render_crop_captured(None, (a["exp"] - b["exp"]).tolist(), rot.tolist(),
                                                          float(st.get("strength", 1.0)), (tl, tr))
                        out["face"] = jpeg_b64(img)
                    except Exception as e:
                        out["face_error"] = f"no face found near the start mark ({e})"
                return out
            return ok(await run(job))
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/video/preview")
    async def vpreview(request):
        """Frames of [start, end] at 24 fps: the video itself, plus the character's face doing it when a picture is
        loaded (relative to the start frame, fine-tuning riding the expression like a taken segment)."""
        try:
            d = await request.json()
            vp = _input_path(d["video"])
            ip = _input_path(d["image"]) if d.get("image") else None

            def job():
                v = video(vp)
                s0 = max(0.0, float(d.get("start", 0)))
                e0 = min(v.count / v.fps, float(d.get("end", s0 + 3)))
                if e0 <= s0:
                    raise ValueError(f"{X.TAG} the end must be after the start")
                if e0 - s0 > MAX_SEGMENT_S:
                    e0 = s0 + MAX_SEGMENT_S
                n = max(2, int(round((e0 - s0) * 24)))
                idx = [int(round((s0 + j / 24.0) * v.fps)) for j in range(n)]
                src = [jpeg_b64(v.frame(i), 420, 78) for i in idx]
                face = None
                if ip:
                    ed = editor_for_file(ip)
                    st = d.get("state") or {}
                    hm = bool(d.get("head_motion", True))
                    tl, tr = tune_pair(st.get("tune"))
                    with torch.inference_mode():
                        i0 = idx[0]
                        ref = v.read(i0, i0)
                        steps = []
                        for i in idx:
                            inf = v.read(i, i0)
                            rot = (inf["rot"] - ref["rot"]) if hm else np.zeros(3)
                            steps.append((None, (inf["exp"] - ref["exp"]).tolist(), rot.tolist(),
                                          float(st.get("strength", 1.0))))
                        face = [jpeg_b64(render_spec(ed, sp), 384, 82) for sp in _captured_plan(steps, tl, tr)]
                warning = ""
                try:
                    with torch.inference_mode():
                        warning = footage_warning(v, idx)
                except Exception:
                    pass
                return {"source": src, "face": face, "fps": 24, "warning": warning}
            return ok(await run(job))
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/video/capture")
    async def vcapture(request):
        try:
            d = await request.json()
            vp = _input_path(d["video"])
            frames, warning = await run(capture_segment, vp, float(d["start"]), float(d["end"]),
                                        bool(d.get("head_motion", True)))
            return ok({"frames": frames, "warning": warning})
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/character")
    async def character(request):
        try:
            d = await request.json()
            state = dict(d["state"])
            state["character"] = X.safe_name(state.get("character", ""))

            def job():
                state["image"] = keep_face(state["image"])
                full, path, hint, _ = make_character_refmod(state)
                return {"refmod": full, "path": path, "folder": os.path.dirname(path), "hint": hint, "state": state}
            return ok(await run(job))
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/library")
    async def library(request):
        """Gallery items; with a picture loaded, each one's peak frame on that face as its thumbnail."""
        try:
            d = await request.json()

            def job():
                items = library_items()
                mine = bool(d.get("use_picture")) and d.get("image")
                for it in items:
                    try:
                        it["thumb"] = thumbnail(d["image"], it) if mine else default_thumbnail(it)
                    except Exception as e:
                        it["thumb_error"] = str(e)
                return {"items": items, "on_picture": bool(mine), "hidden": len(builtin_overrides()["hidden"])}
            return ok(await run(job))
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/delete")
    async def delete(request):
        try:
            d = await request.json()
            if d.get("key"):
                return ok({"deleted": await run(hide_builtin, d["key"])})
            return ok({"deleted": "my/" + await run(delete_expression, d["name"])})
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/rename")
    async def rename(request):
        try:
            d = await request.json()
            return ok({"label": await run(rename_expression, d.get("label"), d.get("key"), d.get("name"))})
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/restore_builtins")
    async def restore(request):
        try:
            return ok({"restored": await run(restore_builtins)})
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/whole_set")
    async def whole_set(request):
        try:
            d = await request.json()
            _no_prompt_guard()
            return ok(await run(make_whole_set, d["image"], d.get("character", "")))
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/open_folder")
    async def open_folder(request):
        try:
            d = await request.json()
            from . import h3md_expression_nodes as N
            root = os.path.normpath(os.path.join(N._refmods_root(), N.SUBFOLDER))
            folder = os.path.normpath(d["folder"])
            if not folder.startswith(root) or not os.path.isdir(folder):
                raise ValueError("not a RefMod expression folder")
            os.startfile(folder)
            return ok({"ok": True})
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/translate")
    async def tr(request):
        try:
            d = await request.json()
            en = await run(translate, d["text"], "en")
            back = await run(translate, en, "zh")
            return ok({"en": en, "back": back})
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/save")
    async def save(request):
        try:
            d = await request.json()
            name = X.safe_name(d.get("name", ""))
            state = d["state"]
            rec = {"format": "h3md-expression", "version": 1, "kind": "studio", "name": name,
                   "label": d.get("label") or name, "en": d.get("description") or state_hint(state), "state": state}
            p = X.save_recipe(rec, overwrite=bool(d.get("overwrite")))
            return ok({"saved": f"my/{name}", "path": p})
        except Exception as e:
            return err(e)

    @routes.post("/h3md_expression/studio/load")
    async def load(request):
        try:
            d = await request.json()
            rec = X.load_recipe("my/" + d["name"])
            return ok({"kind": rec.get("kind"), "state": rec.get("state"), "label": rec.get("label", d["name"]),
                       "description": rec.get("en", "")})
        except Exception as e:
            return err(e)
