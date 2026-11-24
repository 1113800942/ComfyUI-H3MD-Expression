"""H3MD Expression nodes (v0.8).

Pipeline (no hand-tuning on the user's side):
  Studio         live workbench (button on the node): pick a library expression, shape it with sliders, or mark a
                 segment of a video; see the character's face change at once; save to the library or make a RefMod
  RefMod         one click: character + expression -> video RefMod models/refmods/expression/<character>/<expr>
                 (already made with the same settings = reused, nothing is rendered or encoded again)
  RefMod Batch   one click: a character's whole set (built-in styles and/or my/ library)
  Sheet          every style on one face, labelled, to pick from
RefMods are standard ComfyUI-MiniMaxH3Mod files: any H3 workflow that loads RefMods can use them.
"""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

from . import h3md_expression_core as X
from . import h3md_expression_studio as S

VERSION = "0.8.0"
CATEGORY = "MiniMax H3/H3MD/Expression (exp)"
STYLES = ["A", "B", "C", "D"]
SUBFOLDER = "expression"
TUNE_KEYS = ("eyebrow", "eyes_narrow", "smile", "smile_screen_left", "smile_screen_right", "mouth_open",
             "look_x", "look_y", "head_pitch", "head_yaw", "head_roll")


# ----------------------------------------------------------------------------- helpers
def _editor(image, crop_factor):
    """One FaceEditor per input picture (prepare = face detection + feature extraction, done once)."""
    if not hasattr(_editor, "c"):
        _editor.c = {}
    key = (image.data_ptr(), tuple(image.shape), float(image[0].float().mean()), round(crop_factor, 2))
    if key not in _editor.c:
        _editor.c.clear()
        _editor.c[key] = X.FaceEditor(image[0], crop_factor)
    return _editor.c[key]


def _to_tensor(arrs):
    return torch.from_numpy(np.stack(arrs).astype(np.float32) / 255.0)


def _style(expression, style):
    e = X.find(X.load_presets(), expression)
    i = STYLES.index(style)
    if i >= len(e["styles"]):
        raise ValueError(f"{X.TAG} '{e['zh']}' has only {len(e['styles'])} styles "
                         f"({', '.join(STYLES[:len(e['styles'])])})")
    return e, e["styles"][i]


def _tune_inputs():
    f = lambda d, lo, hi, st: ("FLOAT", {"default": d, "min": lo, "max": hi, "step": st})
    return {"strength": f(1.0, 0.0, 2.0, 0.05), "eyebrow": f(0.0, -15.0, 15.0, 0.5),
            "eyes_narrow": f(0.0, -5.0, 20.0, 0.5), "smile": f(0.0, -1.0, 1.3, 0.05),
            "smile_screen_left": f(0.0, -1.0, 1.3, 0.05), "smile_screen_right": f(0.0, -1.0, 1.3, 0.05),
            "mouth_open": f(0.0, -20.0, 80.0, 1.0), "look_x": f(0.0, -15.0, 15.0, 0.5),
            "look_y": f(0.0, -15.0, 15.0, 0.5), "head_pitch": f(0.0, -15.0, 15.0, 0.5),
            "head_yaw": f(0.0, -15.0, 15.0, 0.5), "head_roll": f(0.0, -15.0, 15.0, 0.5)}


def _tune(kw):
    return X.tune_params(eyebrow=kw["eyebrow"], eyes=kw["eyes_narrow"], smile=kw["smile"], mouth_open=kw["mouth_open"],
                         smile_left=kw["smile_screen_left"], smile_right=kw["smile_screen_right"], look_x=kw["look_x"],
                         look_y=kw["look_y"], head_pitch=kw["head_pitch"], head_yaw=kw["head_yaw"],
                         head_roll=kw["head_roll"])


def _peak_index(steps):
    mag = [abs(k) * (np.abs(np.array(er)).sum() if er is not None else 1.0) for ea, er, rr, k in steps]
    return int(np.argmax(mag))


def build(ed, expression, style, strength, tune):
    """-> (face_clip [uint8 crops], keyframes [3 full pictures], hint) for one expression on one face."""
    if expression.startswith("my/"):
        rec = X.load_recipe(expression)
        if rec.get("kind") == "studio":
            st_ = dict(rec["state"]); st_["strength"] = float(st_.get("strength", 1.0)) * strength
            plan = S.frame_plan(st_)
            clip = [S.render_spec(ed, sp) for sp in plan]
            pk = S.peak_index(plan)
            pick = [max(0, pk // 2), pk, min(len(clip) - 1, pk + (len(clip) - pk) // 2)]
            return clip, [ed.paste(clip[i]) for i in pick], f"{rec.get('label', rec['name'])}: {rec.get('en', '')}"
        steps = X.captured_clip_params(rec)
        clip = [ed.render_crop_captured(ea, er, rr, k * strength, tune) for ea, er, rr, k in steps]
        pk = _peak_index(steps)
        pick = [max(0, pk // 2), pk, min(len(clip) - 1, pk + (len(clip) - pk) // 2)]
        frames = [ed.paste(clip[i]) for i in pick]
        return clip, frames, f"{rec.get('label', rec['name'])}: {rec.get('en', '')}"
    e, st = _style(expression, style)
    frames = [ed.render(l, r) for _, l, r in X.frame_params(st, strength, tune)]
    clip = [ed.render_crop(l, r) for l, r in X.clip_params(st, strength, tune)]       # face-only, 39 f @ 24 fps
    return clip, frames, f"{e['en']} ({e['zh']} {st['name']}): {st['en']}"


def _refmod_extract_class():
    """MiniMaxH3RefModExtract of ComfyUI-MiniMaxH3Mod (the same plugin H3MD Director + RefMod loads)."""
    import sys
    for mod in list(sys.modules.values()):
        d = getattr(mod, "__dict__", None)
        c = d.get("MiniMaxH3RefModExtract") if isinstance(d, dict) else None
        if isinstance(c, type) and "execute" in dir(c):
            return c
    raise RuntimeError(f"{X.TAG} ComfyUI-MiniMaxH3Mod is not installed / loaded (needed to save a RefMod).")


def _refmods_root():
    import folder_paths
    try:
        return folder_paths.get_folder_paths("refmods")[0]
    except Exception:
        return os.path.join(folder_paths.models_dir, "refmods")


def _settings_tag(expression, strength, tune_kw, ref_resolution, crop_factor):
    """Default settings -> no suffix; anything changed -> short hash, so a tuned version never replaces the
    default one and the same settings always find the same file again."""
    changed = {k: v for k, v in tune_kw.items() if abs(float(v)) > 1e-9}
    if abs(strength - 1.0) > 1e-9:
        changed["strength"] = strength
    if ref_resolution != 512:
        changed["res"] = ref_resolution
    if abs(crop_factor - 1.7) > 1e-9:
        changed["crop"] = crop_factor
    if not changed:
        return ""
    return "_t" + hashlib.sha1(json.dumps(changed, sort_keys=True).encode()).hexdigest()[:6]


def _hint_of(path):
    try:
        from safetensors import safe_open
        with safe_open(path, "pt") as f:
            return json.loads(f.metadata().get("refmod_meta", "{}")).get("description", "")
    except Exception:
        return ""


def make_refmod(image, character, expression, style, vae, strength=1.0, tune_kw=None, ref_resolution=512,
                crop_factor=1.7, regenerate=False):
    """-> (refmod name for loaders, 'made' | 'reused', hint, face_clip tensor or None)."""
    tune_kw = tune_kw or {k: 0.0 for k in TUNE_KEYS}
    char = X.safe_name(character)
    sub = f"{SUBFOLDER}/{char}"
    if expression.startswith("my/"):
        base = "my_" + expression[3:]
    else:
        base = f"{X.find(X.load_presets(), expression)['id']}_{style}"
    name = X.safe_name(base + _settings_tag(expression, strength, tune_kw, ref_resolution, crop_factor))
    path = os.path.join(_refmods_root(), SUBFOLDER, char, name + ".safetensors")
    full = f"{sub}/{name}"
    if os.path.exists(path) and expression.startswith("my/"):
        try:   # the entry was captured again since this RefMod was made -> make it again
            regenerate = regenerate or os.path.getmtime(path) < os.path.getmtime(os.path.join(X.library_dir(), expression[3:] + ".json"))
        except OSError:
            pass
    if os.path.exists(path) and not regenerate:
        return full, "reused", _hint_of(path), None
    ed = _editor(image, crop_factor)
    clip, _, hint = build(ed, expression, style, strength, X.tune_params() if not any(tune_kw.values()) else _tune(tune_kw))
    clip_t = _to_tensor(clip)
    encode_refmod(clip_t, vae, sub, name, hint, ref_resolution)
    return full, "made", hint, clip_t


def encode_refmod(clip_t, vae, sub, name, hint, ref_resolution):
    C = _refmod_extract_class()
    # one continuous face-only video ref: Full Reference, every frame on the 17k+5 grid, no token cap
    C.execute(name=name, mode="encode", refs_video={"ref_video_1": clip_t}, vae=vae, ref_resolution=ref_resolution,
              latent_frames=int(clip_t.shape[0]), multiplier=1, concept_type="pose_motion", subfolder=sub,
              description=hint, save=True, max_tokens=0, image_refs="stack")


# ----------------------------------------------------------------------------- nodes


class H3MDExpressionStudio:
    """Live expression workbench.  Press "Open Expression Studio": Load Image (the character's final reference
    picture), make the expression with the library, the sliders or a video segment, then
    - "Save expression only (no face)" -> your library (my/<name>), usable on any face
    - "Save character + expression" -> the RefMod models/refmods/expression/<character>/..., made at once.
    Running this node makes (or remakes) the same RefMod from what the studio stored and outputs its name."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "vae": ("VAE",),
            "studio": ("STRING", {"default": "", "multiline": True,
                                  "tooltip": "Filled by the Expression Studio (press the button); not meant for typing"}),
            "ref_resolution": ("INT", {"default": 512, "min": 256, "max": 1024, "step": 64}),
        }}

    RETURN_TYPES = ("STRING", "STRING", "IMAGE")
    RETURN_NAMES = ("refmod_name", "prompt_hint", "face_clip")
    FUNCTION = "run"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def run(self, vae, studio, ref_resolution):
        if not (studio or "").strip():
            raise ValueError(f"{X.TAG} open the Expression Studio, load the character's picture, make the expression "
                             "and press 'Save character + expression'")
        state = json.loads(studio)
        if not state.get("character"):
            raise ValueError(f"{X.TAG} type the character's name in the Expression Studio")
        full, path, hint, clip = S.make_character_refmod(state, ref_resolution, vae)
        return {"ui": {"text": [f"made: {full}"]}, "result": (full, hint, _to_tensor(clip))}



def _font(size):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


NODE_CLASS_MAPPINGS = {
    "H3MDExpressionStudio": H3MDExpressionStudio,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "H3MDExpressionStudio": f"H3MD Expression Studio v{VERSION}",
}
