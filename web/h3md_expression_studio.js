// H3MD Expression Studio - live expression workbench (front end).
// Pattern from AnyAngle Studio T8: a button on the node opens a full-screen dialog; the face is rendered by the
// backend routes /h3md_expression/studio/*; "Apply" writes the state JSON into the node's `studio` widget.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE = "H3MDExpressionStudio";

// ---------- language: follows ComfyUI's own language setting (Comfy.Locale); Chinese for zh*, English otherwise
const LANG = () => {
  let l = "";
  try { l = app.ui?.settings?.getSettingValue?.("Comfy.Locale") || ""; } catch { /* old frontends */ }
  return (l || navigator.language || "en").toLowerCase().startsWith("zh") ? "zh" : "en";
};
const TX = (en, zh) => (LANG() === "zh" ? zh : en);
// labels sent by the backend as "English 中文": show one language
const T2 = t => {
  if (!t || !/[\u3400-\u9fff]/.test(t)) return t;
  let j = t.search(/[\u3400-\u9fff\uff08]/);
  while (j > 0 && "0123456789 ".includes(t[j - 1])) j--;
  return TX(t.slice(0, j).trim() || t, t.slice(j).trim());
};

const R = "/h3md_expression/studio";
const CSS = `
.h3x-dlg{width:min(1500px,97vw);height:94vh;max-width:none;max-height:none;padding:0;border:1px solid #3a5265;border-radius:12px;background:#101920;color:#dce6ee;font:13px system-ui,sans-serif}
.h3x-dlg::backdrop{background:rgba(0,0,0,.6)}
.h3x-wrap{display:flex;flex-direction:column;height:100%}
.h3x-head{display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:10px 14px;border-bottom:1px solid #26384a}
.h3x-head b{font-size:15px}.h3x-head .sp{flex:1}
.h3x-body{flex:1;display:grid;grid-template-columns:minmax(360px,1fr) 420px;gap:14px;padding:14px;overflow:hidden}
.h3x-left{display:flex;flex-direction:column;gap:8px;min-height:0}
.h3x-view{flex:1;display:flex;gap:10px;min-height:0}
.h3x-pane{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#0a1117;border:1px solid #22323f;border-radius:8px;position:relative;min-height:0}
.h3x-pane img{max-width:100%;max-height:100%;object-fit:contain}
.h3x-pane .cap{position:absolute;top:6px;left:8px;color:#8fb3c9;font-size:12px}
.h3x-right{overflow:auto;display:flex;flex-direction:column;gap:12px;padding-right:4px}
.h3x-box{border:1px solid #26384a;border-radius:8px;padding:10px;display:flex;flex-direction:column;gap:8px}
.h3x-box h4{margin:0;font-size:13px;color:#9cc3dc}
.h3x-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.h3x-row label{min-width:150px}
.h3x-row input[type=range]{flex:1;min-width:120px}
.h3x-row .v{width:46px;text-align:right;color:#ffd75e;font-variant-numeric:tabular-nums}
.h3x-dlg button{background:#1f3344;color:#dce6ee;border:1px solid #35506a;border-radius:6px;padding:5px 10px;cursor:pointer}
.h3x-dlg button:hover{background:#28445a}.h3x-dlg button.pri{background:#2b6cb0;border-color:#3b82c4}
.h3x-dlg button.on{background:#3b82c4}.h3x-dlg button:disabled{opacity:.45;cursor:default}
.h3x-dlg select,.h3x-dlg input[type=text]{background:#0d1820;color:#dce6ee;border:1px solid #35506a;border-radius:6px;padding:4px 6px}
.h3x-tabs{display:flex;gap:6px}
.h3x-status{color:#8fb3c9;min-height:18px}.h3x-err{color:#ff8a80}
.h3x-mark{color:#ffd75e}
.h3x-grp{margin-top:6px;padding-top:6px;border-top:1px dashed #2c4256;color:#7fd1ff;font-weight:600}
.h3x-pane{overflow:hidden}.h3x-pane img{transform-origin:center center;cursor:grab;user-select:none;-webkit-user-drag:none}
.h3x-zoom{position:absolute;right:8px;bottom:8px;display:flex;gap:4px;z-index:2}
.h3x-zoom button{padding:2px 9px;font-size:15px;line-height:20px}
.h3x-dlg button.blue{background:#2b6cb0;border-color:#3b82c4}.h3x-dlg button.green{background:#2f855a;border-color:#48a874}
.h3x-head label{color:#8fb3c9}.h3x-path{font-family:monospace;font-size:12px;color:#c7f0d0;word-break:break-all}
.h3x-vbar{display:none;flex-direction:column;gap:6px;margin:0;padding:8px 10px;border:1px solid #3a5a74;border-radius:8px;background:#0e1d2a}
.h3x-name{color:#c7d8e4;font-size:12px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.h3x-sep{width:1px;height:24px;background:#35506a}
.h3x-warn{color:#ffc46b}
.h3x-gal{position:absolute;inset:0;background:#0c151c;display:none;flex-direction:column;z-index:5}
.h3x-gal-head{display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid #26384a}
.h3x-gal-head .sp{flex:1}.h3x-gal-head input[type=text]{width:240px}
.h3x-picopt{display:flex;align-items:center;gap:6px;margin-left:14px;padding:4px 8px;border:1px solid #2c4256;border-radius:6px}
.h3x-picopt label{display:flex;align-items:center;gap:5px;cursor:pointer}
.h3x-gal-body{flex:1;display:flex;min-height:0}
.h3x-gal-side{width:170px;border-right:1px solid #26384a;padding:10px;display:flex;flex-direction:column;gap:4px}
.h3x-gal-side div{padding:7px 10px;border-radius:6px;cursor:pointer;display:flex;justify-content:space-between}
.h3x-gal-side div.on{background:#2b6cb0}
.h3x-gal-grid{flex:1;overflow:auto;padding:14px;display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px;align-content:start;grid-auto-rows:max-content}
.h3x-card{background:#15222d;border:1px solid #2c4256;border-radius:8px;overflow:hidden;cursor:pointer;display:flex;flex-direction:column}
.h3x-card:hover{border-color:#5aa0d8}.h3x-card.on{border:2px solid #4f9be0}
.h3x-card .th{aspect-ratio:1;flex-shrink:0;background:#0a1117;display:flex;align-items:center;justify-content:center;color:#5d7a8f;font-size:12px;text-align:center;padding:6px}
.h3x-card .th img{width:100%;height:100%;object-fit:cover}
.h3x-card .t{padding:6px 8px 2px;font-weight:600;font-size:13px}.h3x-card .s{padding:0 8px 8px;color:#8fb3c9;font-size:11px}
.h3x-card{position:relative}
.h3x-del{position:absolute;top:6px;right:6px;width:26px;height:26px;padding:0 !important;border-radius:50% !important;background:rgba(20,0,0,.75) !important;border-color:#a33 !important;color:#ff9a9a !important;font-size:14px;line-height:24px}
.h3x-del:hover{background:#a33 !important;color:#fff !important}
.h3x-card .t{display:flex;align-items:center;gap:4px}.h3x-card .t span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.h3x-ren{padding:0 6px !important;height:22px;font-size:12px;font-weight:400;flex-shrink:0}
.h3x-restore{margin:10px 8px;font-size:12px}
.h3x-gal-note{padding:8px 16px;color:#8fb3c9;border-bottom:1px solid #26384a;font-size:12px}
.h3x-tr{border:1px solid #3b82c4;border-radius:6px;padding:8px;display:none;flex-direction:column;gap:6px;background:#0e1d2a}
`;

function css() {
  if (document.getElementById("h3x-css")) return;
  const s = document.createElement("style"); s.id = "h3x-css"; s.textContent = CSS; document.head.append(s);
}

const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
};

async function post(path, body) {
  const r = await api.fetchApi(R + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const d = await r.json();
  if (!r.ok || d.error) throw new Error(d.error || r.statusText);
  return d;
}

function parseAnnotated(v) {
  if (!v || typeof v !== "string") return null;
  let type = "input";
  const m = v.match(/^(.*) \[(input|output|temp)\]$/);
  if (m) { v = m[1]; type = m[2]; }
  const i = v.lastIndexOf("/");
  return { filename: i >= 0 ? v.slice(i + 1) : v, subfolder: i >= 0 ? v.slice(0, i) : "", type };
}

async function upload(file, subfolder) {
  const fd = new FormData();
  fd.append("image", file); fd.append("subfolder", subfolder); fd.append("type", "input"); fd.append("overwrite", "false");
  const r = await api.fetchApi("/upload/image", { method: "POST", body: fd });
  if (!r.ok) throw new Error("upload failed");
  const d = await r.json();
  return { filename: d.name, subfolder: d.subfolder || "", type: "input" };
}

function addZoom(pane, img) {
  let s = 1, x = 0, y = 0, drag = null;
  const apply = () => { img.style.transform = `translate(${x}px,${y}px) scale(${s})`; };
  const set = (ns) => { s = Math.min(8, Math.max(1, ns)); if (s === 1) { x = 0; y = 0; } apply(); };
  pane.addEventListener("wheel", e => { e.preventDefault(); set(s * (e.deltaY < 0 ? 1.15 : 1 / 1.15)); }, { passive: false });
  pane.addEventListener("pointerdown", e => { if (s === 1 || e.target.tagName === "BUTTON") return; drag = { px: e.clientX, py: e.clientY, x, y }; pane.setPointerCapture(e.pointerId); });
  pane.addEventListener("pointermove", e => { if (!drag) return; x = drag.x + e.clientX - drag.px; y = drag.y + e.clientY - drag.py; apply(); });
  pane.addEventListener("pointerup", () => { drag = null; });
  pane.addEventListener("dblclick", e => { if (e.target.tagName !== "BUTTON") set(1); });
  const b = (t, f, tip) => { const k = document.createElement("button"); k.textContent = t; k.title = tip; k.addEventListener("click", ev => { ev.stopPropagation(); f(); }); return k; };
  const bar = document.createElement("div"); bar.className = "h3x-zoom";
  bar.append(b("−", () => set(s / 1.25), TX("Zoom out", "缩小")), b("+", () => set(s * 1.25), TX("Zoom in", "放大")), b("⟲", () => set(1), TX("Reset", "还原")));
  pane.append(bar);
}

const DEFAULT = () => ({ version: 1, base: { kind: "none" }, strength: 1, tune: {}, head_motion: true, label: "", description: "" });

function openStudio(node) {
  css();
  const widget = node.widgets.find(w => w.name === "studio");
  let state; try { state = widget.value ? JSON.parse(widget.value) : DEFAULT(); } catch { state = DEFAULT(); }
  state = Object.assign(DEFAULT(), state);
  let savedName = state.saved_name || null; delete state.saved_name;
  let face = state.image || null;
  let meta = null, undo = [], redo = [], frames = 39, peak = 14, frame = null;
  let busy = false, pending = false, playing = null, video = null, vinfo = null, mark = { start: null, end: null };

  const dlg = el("dialog", { class: "h3x-dlg" });
  const status = el("div", { class: "h3x-status" });
  const setStatus = (t, bad) => { status.textContent = t || ""; status.className = "h3x-status" + (bad ? " h3x-err" : ""); };
  const warn = t => { status.textContent = t; status.className = "h3x-status h3x-warn"; };
  const faceImg = el("img"), srcImg = el("img");
  const facePane = el("div", { class: "h3x-pane" }, el("span", { class: "cap" }, TX("Character", "角色")), faceImg);
  const srcPane = el("div", { class: "h3x-pane", style: "display:none" }, el("span", { class: "cap" }, TX("Video", "视频")), srcImg);
  addZoom(facePane, faceImg); addZoom(srcPane, srcImg);
  const tl = el("input", { type: "range", min: 0, max: 38, step: 1, value: 14, style: "flex:1" });
  const tlLabel = el("span", { class: "v", style: "width:90px" }, "");
  const playBtn = el("button", {}, TX("▶ Play", "▶ 播放"));
  const peakBtn = el("button", {}, TX("Peak", "最强"));
  const exportBtn = el("button", { class: "blue", onclick: () => exportImage(),
    title: TX("Save the frame the timeline is on as a full-size picture (your photo with this expression) in ComfyUI's output folder",
              "把时间轴停着的这一帧存成整张原尺寸图片（你的照片换上这个表情），放在 ComfyUI 的 output 文件夹") }, TX("Export image", "导出图片"));
  const faceOnly = el("input", { type: "checkbox" });
  const faceOnlyLbl = el("label", { style: "min-width:0;white-space:nowrap", title: TX("Export only the face area (512 x 512) instead of the whole picture",
    "只导出脸部那一块（512x512），不导出整张图") }, faceOnly, TX(" Face only", " 只要脸部"));

  // ---------- source tabs
  const tabs = {};
  const panels = {};
  const tabBar = el("div", { class: "h3x-tabs" });
  const libLabel = el("span", { style: "flex:1;color:#ffd75e" }, "");
  panels.library = el("div", { class: "h3x-row" }, el("span", { style: "color:#8fb3c9" }, TX("Currently using:", "当前用的：")), libLabel, el("button", { onclick: () => openGallery() }, TX("Open library", "打开表情库")));
  panels.none = el("div", { class: "h3x-row" }, el("span", {}, TX("Shape the face with the sliders below.", "直接拖下面的滑块捏表情。")));
  const vidName = el("span", { class: "h3x-name" }, "");
  const loadVidBtn = el("button", { class: "blue", onclick: () => vidUp.click() }, TX("Load Video", "加载视频"));
  const vidUp = el("input", { type: "file", accept: "video/*", style: "display:none" });
  const vt = el("input", { type: "range", min: 0, max: 1, step: 0.01, value: 0, style: "flex:1" });
  const vtLabel = el("span", { class: "v", style: "width:60px" }, "0.00s");
  const markLabel = el("span", { class: "h3x-mark" }, "");
  const hm = el("input", { type: "checkbox" });
  const useSeg = el("button", { class: "pri" }, TX("Use this segment", "用这一段"));
  const segInfo = el("div", {}, "");
  panels.video = el("div", { style: "display:flex;flex-direction:column;gap:6px" }, segInfo,
    el("div", { style: "color:#8fb3c9" }, TX("Open the library to switch, or press Reset to go back to the calm face.", "要换就打开表情库；点“重置”回到平静脸。")));
  const vbar = el("div", { class: "h3x-vbar" },
    el("div", { class: "h3x-row" }, el("b", {}, TX("Video segment", "视频选段")), vt, vtLabel),
    el("div", { class: "h3x-row" },
      el("button", { onclick: () => setMark("start") }, TX("Set start", "设起点")),
      el("button", { onclick: () => setMark("end") }, TX("Set end", "设终点")), markLabel,
      el("label", { style: "min-width:0" }, hm, TX(" Keep head moves", " 保留头部动作")), useSeg,
      el("button", { onclick: () => closeVideo(), title: TX("Hide the video", "关闭视频") }, TX("✕ Close video", "✕ 关闭视频"))),
    el("div", { style: "color:#8fb3c9" }, TX("Drag to the calm moment just before the expression → Set start; drag to where it ends → Set end. Works best on a close-up, face toward the camera, head still.", "拖到表情开始前的平静处设起点，拖到表情结束处设终点。最适合：近景、正脸、头不怎么动。")));

  // ---------- sliders
  const sliders = {};
  const sliderBox = el("div", { class: "h3x-box" }, el("h4", {}, TX("Fine-tune (double-click a slider to zero it)", "微调（双击滑块归零）")));

  // ---------- actions
  const undoBtn = el("button", { onclick: () => doUndo() }, TX("↶ Undo", "↶ 撤销"));
  const redoBtn = el("button", { onclick: () => doRedo() }, TX("↷ Redo", "↷ 重做"));
  const resetBtn = el("button", { onclick: () => { push(); state = DEFAULT(); syncAll(); refresh(); } }, TX("Reset", "重置"));
  const nameIn = el("input", { type: "text", placeholder: TX("file name (English letters)", "文件名（英文）"), style: "flex:1" });
  const labelIn = el("input", { type: "text", placeholder: TX("label, e.g. Self-absorbed", "显示名，例如：自我陶醉"), style: "flex:1" });
  const descIn = el("input", { type: "text", placeholder: TX("Description (any language, turned into English when saving)", "描述（可写中文，存时自动翻成英文）"), style: "flex:1" });
  const trEn = el("input", { type: "text", style: "flex:1" });
  const trBack = el("span", { style: "color:#8fb3c9" });
  const trBox = el("div", { class: "h3x-tr" },
    el("div", {}, TX("English for prompts (you can edit it):", "英文描述（可改）：")), el("div", { class: "h3x-row" }, trEn),
    el("div", {}, TX("Back-translation check: ", "回译核对："), trBack),
    el("div", { class: "h3x-row" }, el("button", { class: "pri", onclick: () => { trBox.style.display = "none"; doSave(trEn.value); } }, TX("Confirm & save", "确认保存")),
      el("button", { onclick: () => { trBox.style.display = "none"; } }, TX("Cancel", "取消"))));
  const ow = el("input", { type: "checkbox" });
  const saveBtn = el("button", { class: "blue", onclick: () => save() }, TX("Save expression only (no face)", "只存表情（不带脸）"));
  const charBtn = el("button", { class: "green", onclick: () => saveCharacter() }, TX("Save character + expression", "保存人物＋表情"));
  const pathTxt = el("div", { class: "h3x-path" });
  let lastFolder = null;
  // after saving: show the prompt line to paste into the shot (the path itself is only behind Copy path)
  const pathRow = el("div", { style: "display:none;flex-direction:column;gap:6px" },
    el("div", {}, TX("RefMod saved. Prompt for this expression (paste it into the shot's prompt):", "已生成。这个表情的提示词（贴到镜头的提示词里）：")), pathTxt,
    el("div", { class: "h3x-row" },
      el("button", { class: "pri", onclick: () => { navigator.clipboard?.writeText(pathTxt.textContent || ""); setStatus(TX("Prompt copied", "提示词已复制")); } }, TX("Copy prompt", "复制提示词")),
      el("button", { onclick: () => { navigator.clipboard?.writeText(pathTxt.dataset.path || ""); setStatus(TX("Path copied", "路径已复制")); } }, TX("Copy path", "复制路径")),
      el("button", { onclick: () => post("/open_folder", { folder: lastFolder }).catch(e => setStatus(e.message, true)) }, TX("Open folder", "打开文件夹"))));
  const faceUp = el("input", { type: "file", accept: "image/*", style: "display:none" });
  const imgName = el("span", { class: "h3x-name" }, "");
  const loadImgBtn = el("button", { class: "blue", onclick: () => faceUp.click() }, TX("Load Image", "加载图片"));
  const reloadBtn = el("button", { onclick: () => loadFace(true), title: TX("Read the picture again", "重新读取图片") }, TX("⟳ Reload", "⟳ 重新载入"));
  const charIn = el("input", { type: "text", placeholder: TX("character name, e.g. eva / zhangsan", "角色名（英文或拼音），例如 eva / zhangsan"), style: "flex:1" });
  const wholeBtn = el("button", { class: "green", onclick: () => wholeSet(), title: TX("Make this character's RefMod for every expression in the library", "给这个人把表情库里每个表情都做成 RefMod") }, TX("Whole set", "整套生成"));
  charIn.value = state.character || "";
  charIn.addEventListener("input", () => { state.character = charIn.value.trim(); });
  const right = el("div", { class: "h3x-right" },
    el("div", { class: "h3x-box" }, el("h4", {}, TX("Expression source", "表情来源")), panels.library, panels.video),
    sliderBox,
    el("div", { class: "h3x-box" }, el("h4", {}, TX("Edit", "编辑")), el("div", { class: "h3x-row" }, undoBtn, redoBtn, resetBtn)),
    el("div", { class: "h3x-box" }, el("h4", {}, TX("Save", "保存")),
      el("div", { class: "h3x-row" }, nameIn), el("div", { class: "h3x-row" }, labelIn), el("div", { class: "h3x-row" }, descIn),
      el("div", { class: "h3x-row" }, saveBtn, el("label", { style: "min-width:0" }, ow, TX(" overwrite same name", " 覆盖同名"))), trBox,
      el("div", { style: "color:#8fb3c9" }, TX("Expression only = usable on any face.", "只存表情：以后任何人都能套用。")),
      el("div", { class: "h3x-row" }, el("label", { style: "min-width:0" }, TX("Character", "角色名")), charIn),
      el("div", { class: "h3x-row" }, charBtn, wholeBtn),
      el("div", { style: "color:#8fb3c9" }, TX("Character + expression = this face doing this expression, made into a RefMod under the character's name.", "保存人物＋表情：用这张脸做成 RefMod，存在角色名下面。")),
      pathRow));
  const left = el("div", { class: "h3x-left" }, vbar,
    el("div", { class: "h3x-view" }, srcPane, facePane),
    el("div", { class: "h3x-row" }, playBtn, peakBtn, tl, tlLabel, exportBtn, faceOnlyLbl), status);
  dlg.append(el("div", { class: "h3x-wrap" },
    el("div", { class: "h3x-head" }, el("b", {}, TX("H3MD Expression Studio", "表情工作台")),
      loadImgBtn, faceUp, imgName, reloadBtn,
      el("span", { class: "h3x-sep" }), loadVidBtn, vidUp, vidName,
      el("span", { class: "sp" }),
      el("button", { onclick: () => close() }, "✕")),
    el("div", { class: "h3x-body" }, left, right)));
  document.body.append(dlg);
  // a file picker's Cancel also fires a bubbling "cancel" event; only Esc on the studio itself closes it
  dlg.addEventListener("cancel", e => { if (e.target !== dlg) return; e.preventDefault(); close(); });

  // ---------- state helpers
  const snap = () => JSON.stringify(state);
  function push() { undo.push(snap()); if (undo.length > 100) undo.shift(); redo = []; savedName = null; buttons(); }
  function doUndo() { if (!undo.length) return; redo.push(snap()); state = JSON.parse(undo.pop()); syncAll(); refresh(); }
  function doRedo() { if (!redo.length) return; undo.push(snap()); state = JSON.parse(redo.pop()); syncAll(); refresh(); }
  function buttons() { undoBtn.disabled = !undo.length; redoBtn.disabled = !redo.length; }

  function close() { stop(); storeOnNode(); dlg.close(); dlg.remove(); }

  function storeOnNode() {
    const out = JSON.parse(snap());
    if (savedName) out.saved_name = savedName;
    if (face) out.image = face;
    out.character = charIn.value.trim();
    widget.value = JSON.stringify(out); widget.callback?.(widget.value);
    app.graph.setDirtyCanvas(true, true);
  }

  function nameMissing() {
    setStatus(TX("Type the character's name just above the green button (English letters or pinyin, e.g. lisi).", "请在绿色按钮上面填角色名（英文或拼音）。"), true);
    charIn.style.borderColor = "#ff6b6b"; charIn.focus();
    setTimeout(() => { charIn.style.borderColor = ""; }, 4000);
  }
  async function wholeSet() {
    const ch = charIn.value.trim();
    if (!face) { setStatus(TX("Load the character's picture first.", "请先加载图片。"), true); return; }
    if (!/^[A-Za-z0-9_\-]+$/.test(ch)) { nameMissing(); return; }
    wholeBtn.disabled = true; charBtn.disabled = true;
    setStatus(TX("Making the whole set…", "正在整套生成（每个表情几秒钟，已有的会跳过）"));
    try {
      const r = await post("/whole_set", { image: face, character: ch });
      pathTxt.textContent = r.folder; pathTxt.dataset.path = r.folder; lastFolder = r.folder; pathRow.style.display = "flex";
      setStatus(TX(`Whole set for ${ch}: ${r.made.length} made, ${r.skipped.length} already there${r.failed.length ? ", " + r.failed.length + " failed: " + r.failed.join("; ") : ""}.`, `${ch} 整套完成：新做 ${r.made.length} 个，已有 ${r.skipped.length} 个${r.failed.length ? "，失败 " + r.failed.length + " 个：" + r.failed.join("；") : ""}。`), !!r.failed.length);
      state.character = ch; storeOnNode();
    } catch (e) { setStatus(e.message, true); }
    wholeBtn.disabled = false; charBtn.disabled = false;
  }
  async function saveCharacter() {
    const ch = charIn.value.trim();
    if (!face) { setStatus(TX("Load the character's picture first.", "请先加载图片。"), true); return; }
    if (!/^[A-Za-z0-9_\-]+$/.test(ch)) { nameMissing(); return; }
    charBtn.disabled = true; setStatus(TX("Making the RefMod…", "正在生成 RefMod（第一次要加载 VAE，约十几秒）"));
    try {
      const st = JSON.parse(snap()); if (savedName) st.saved_name = savedName; st.image = face; st.character = ch;
      const r = await post("/character", { state: st });
      face = r.state.image; state.image = face; state.character = ch; setImgName();
      pathTxt.textContent = r.hint || ""; pathTxt.dataset.path = r.path; lastFolder = r.folder; pathRow.style.display = "flex";
      setStatus(TX(`Saved: ${r.refmod} — in the Director, add it to a shot as a RefMod.`, `已生成，在导演台里把它加到镜头的 RefMod 上。`));
      storeOnNode();
    } catch (e) { setStatus(e.message, true); }
    charBtn.disabled = false;
  }

  async function save() {
    const d = descIn.value.trim();
    if (/[\u3400-\u9fff]/.test(d)) {
      saveBtn.disabled = true; setStatus(TX("Translating to English…", "正在翻译（第一次要加载翻译模型，约十几秒）"));
      try {
        const r = await post("/translate", { text: d });
        trEn.value = r.en; trBack.textContent = r.back; trBox.style.display = "flex";
        setStatus(TX("Check the English, edit if needed, then Confirm & save.", "核对一下英文，再点确认保存。"));
      } catch (e) { setStatus(e.message, true); }
      saveBtn.disabled = false; return;
    }
    doSave(d);
  }
  async function doSave(desc) {
    try {
      const r = await post("/save", { state, name: nameIn.value, label: labelIn.value, description: desc, overwrite: ow.checked });
      savedName = r.saved.slice(3); state.label = labelIn.value; state.description = desc;
      setStatus(TX(`Saved ${r.saved} — it now appears as ${r.saved} in every expression list.`, `已存进表情库。`));
      galItems = []; meta = await (await api.fetchApi(R + "/meta")).json(); fillLibrary();
    } catch (e) { setStatus(e.message, true); }
  }

  // ---------- rendering (one request in flight, latest wins)
  async function refresh(atFrame) {
    if (atFrame !== undefined) frame = atFrame;
    if (!face) { if (!video) setStatus(TX("Load Image at the top to see the expression on a face.", "在顶上加载图片，就能看到表情套在脸上的样子。")); return; }
    if (busy) { pending = true; return; }
    busy = true;
    try {
      const slow = setTimeout(() => setStatus(TX("Still loading after 30 s — the GPU may be busy with another job. Press Reload to try again.", "30 秒还没好：显卡可能在忙别的任务，可以点 Reload 重新载入。"), true), 30000);
      let d; try { d = await post("/render", { image: face, state, frame: frame == null ? "peak" : frame }); } finally { clearTimeout(slow); }
      faceImg.src = d.image; frames = d.frames; peak = d.peak;
      tl.max = frames - 1; tl.value = d.frame; tlLabel.textContent = `${d.frame + 1}/${frames} f`;
      if (status.classList.contains("h3x-err")) setStatus("");
    } catch (e) { setStatus(e.message, true); }
    busy = false;
    if (pending) { pending = false; refresh(); }
  }

  async function play() {
    if (playing) { stop(); return; }
    if (!video && !face) { setStatus(TX("Load Image or Load Video first.", "请先加载图片或视频。"), true); return; }
    playBtn.textContent = "… rendering"; playBtn.disabled = true;
    try {
      let src = null, faces = null, fps = 24;
      if (video) {           // the marked stretch of the video (and the face doing it, when a picture is loaded)
        const s0 = mark.start ?? +vt.value;
        const e0 = mark.end != null && mark.end > s0 ? mark.end : Math.min(vinfo.duration, s0 + 3);
        const d = await post("/video/preview", { video, image: face, start: s0, end: e0, head_motion: hm.checked, state });
        src = d.source; faces = d.face; fps = d.fps;
        if (d.warning) warn(TX(d.warning.en, d.warning.zh));
      } else {               // the expression on the character's face
        const d = await post("/clip", { image: face, state });
        faces = d.frames; fps = d.fps;
      }
      const n = (src || faces).length;
      let i = 0; playBtn.disabled = false; playBtn.textContent = TX("■ Stop", "■ 停止");
      playing = setInterval(() => {
        if (src) srcImg.src = src[i];
        if (faces) faceImg.src = faces[i];
        tl.max = n - 1; tl.value = i; tlLabel.textContent = `${i + 1}/${n} f`;
        i = (i + 1) % n;
      }, 1000 / fps);
    } catch (e) { setStatus(e.message, true); playBtn.disabled = false; playBtn.textContent = TX("▶ Play", "▶ 播放"); }
  }
  function stop() { if (playing) clearInterval(playing); playing = null; playBtn.textContent = TX("▶ Play", "▶ 播放"); playBtn.disabled = false; }

  // ---------- sliders
  function buildSliders() {
    const mk = (k, label, lo, hi, st) => {
      const r = el("input", { type: "range", min: lo, max: hi, step: st });
      const v = el("span", { class: "v" });
      let dragging = false;
      r.addEventListener("input", () => {
        if (!dragging) { push(); dragging = true; }
        setVal(k, parseFloat(r.value)); v.textContent = (+r.value).toFixed(2); stop(); frame = null; refresh();
      });
      r.addEventListener("change", () => { dragging = false; });
      r.addEventListener("dblclick", () => { push(); setVal(k, k === "strength" ? 1 : 0); syncSliders(); refresh(); });
      sliders[k] = { r, v };
      sliderBox.append(el("div", { class: "h3x-row" }, el("label", {}, label), r, v));
    };
    mk("strength", TX("Strength (whole expression)", "整体强度"), ...meta.tune.strength);
    for (const [title, items] of meta.groups) {
      sliderBox.append(el("div", { class: "h3x-grp" }, T2(title)));
      for (const [k, label, lo, hi, st] of items) mk(k, T2(label), lo, hi, st);
    }
  }
  const getVal = k => k === "strength" ? (state.strength ?? 1) : (state.tune?.[k] ?? 0);
  function setVal(k, x) { if (k === "strength") state.strength = x; else { state.tune = state.tune || {}; state.tune[k] = x; } }
  function syncSliders() { for (const k of Object.keys(sliders)) { const x = getVal(k); sliders[k].r.value = x; sliders[k].v.textContent = (+x).toFixed(2); } }

  // ---------- library gallery
  const galGrid = el("div", { class: "h3x-gal-grid" });
  const galSide = el("div", { class: "h3x-gal-side" });
  const galSearch = el("input", { type: "text", placeholder: TX("Search by name", "搜索：名称") });
  const galCount = el("span", { style: "color:#8fb3c9" });
  const usePic = el("input", { type: "checkbox" });
  const usePicBtn = el("button", { onclick: () => refreshGallery() }, TX("Apply", "确定"));
  const gal = el("div", { class: "h3x-gal" },
    el("div", { class: "h3x-gal-head" }, el("b", {}, TX("Expression library", "表情库")), galCount,
      el("div", { class: "h3x-picopt" }, el("label", {}, usePic, TX("Use my loaded picture for the thumbnails", "用我加载的图片画缩略图")), usePicBtn),
      el("span", { class: "sp" }), galSearch,
      el("button", { onclick: () => { gal.style.display = "none"; } }, "✕")),
    el("div", { class: "h3x-gal-note" }, TX("Expressions here carry no face: the face on the thumbnails is only a preview. Deleting one removes the expression only; RefMods already made stay in their character folders.",
      "这里的表情都不带脸，缩略图上的脸只是预览。删除只删表情本身，已经做好的 RefMod 仍在各自的角色文件夹里。")),
    el("div", { class: "h3x-gal-body" }, galSide, galGrid));
  dlg.append(gal);
  let galItems = [], galCat = "all", galFace = null, galHidden = 0;
  const sameBase = (a, b) => a && b && a.kind === b.kind && (a.kind === "preset" ? a.expression === b.expression && a.style === b.style : a.name === b.name);
  function libText() {
    const it = galItems.find(x => sameBase(x.base, state.base));
    const k = state.base.kind;
    libLabel.textContent = it ? `${TX(it.title_en || it.title, it.title)} — ${it.sub}`
      : k === "video" ? TX("Video segment", "视频片段")
      : k === "none" ? TX("Calm face (sliders only)", "平静脸（只用滑块）")
      : (k === "my" ? `my/${state.base.name}` : TX("(selected)", "（已选）"));
  }
  function drawGallery() {
    const q = galSearch.value.trim().toLowerCase();
    const cats = [["all", TX("All", "全部")], ["builtin", TX("Built-in", "内置")], ["mine", TX("My expressions", "我的表情")]];
    galSide.innerHTML = "";
    for (const [k, t] of cats) {
      const n = galItems.filter(x => k === "all" || x.cat === k).length;
      const row = el("div", { class: galCat === k ? "on" : "", onclick: () => { galCat = k; drawGallery(); } }, el("span", {}, t), el("span", {}, String(n)));
      galSide.append(row);
    }
    if (galHidden > 0) galSide.append(el("button", { class: "h3x-restore", onclick: () => restoreBuiltins() },
      TX(`Restore deleted built-ins (${galHidden})`, `恢复删掉的内置表情（${galHidden}）`)));
    const shown = galItems.filter(x => (galCat === "all" || x.cat === galCat) && (!q || (x.title + " " + x.sub).toLowerCase().includes(q)));
    galCount.textContent = `${shown.length} / ${galItems.length}`;
    galGrid.innerHTML = "";
    for (const it of shown) {
      const th = el("div", { class: "th" }, it.thumb ? el("img", { src: it.thumb }) : TX("No preview", "无预览"));
      const card = el("div", { class: "h3x-card" + (sameBase(it.base, state.base) ? " on" : ""), onclick: () => pick(it) },
        th, el("div", { class: "t" }, el("span", { title: TX(it.title_en || it.title, it.title) }, TX(it.title_en || it.title, it.title)),
          el("button", { class: "h3x-ren", title: TX("Rename", "改名"), onclick: ev => { ev.stopPropagation(); renameExpr(it); } }, TX("Rename", "改名"))),
        el("div", { class: "s" }, it.cat === "builtin" ? TX("Built-in", "内置") + " · " + it.key.slice(-1) : it.sub));
      card.append(el("button", { class: "h3x-del", title: TX("Delete this expression", "删除这个表情"), onclick: ev => { ev.stopPropagation(); delExpr(it); } }, "✕"));
      galGrid.append(card);
    }
  }
  async function delExpr(it) {
    const nm = TX(it.title_en || it.title, it.title);
    const builtin = it.cat === "builtin";
    if (!confirm(builtin
        ? TX(`Remove "${nm}" from the library? Built-in expressions can be brought back with "Restore deleted built-ins". RefMods already made are kept.`,
             `从表情库删除“${nm}”？内置表情删了以后可以用“恢复删掉的内置表情”找回来。已经做好的 RefMod 会保留。`)
        : TX(`Delete "${nm}" from your library? The expression is removed; RefMods already made are kept.`,
             `从表情库删除“${nm}”？只删表情本身，已经做好的 RefMod 会保留。`))) return;
    try {
      await post("/delete", builtin ? { key: it.key } : { name: it.base.name });
      galItems = galItems.filter(x => x !== it);
      if (builtin) galHidden++;
      if (sameBase(it.base, state.base)) { push(); state.base = { kind: "none" }; syncAll(); refresh(); }
      drawGallery(); libText(); setStatus(TX(`Deleted "${nm}".`, `已删除“${nm}”。`));
    } catch (e) { setStatus(e.message, true); }
  }
  async function renameExpr(it) {
    const old = TX(it.title_en || it.title, it.title);
    const nv = prompt(TX("New name for this expression:", "给这个表情起个新名字："), old);
    if (nv === null || !nv.trim() || nv.trim() === old) return;
    try {
      const r = await post("/rename", it.cat === "builtin" ? { key: it.key, label: nv.trim() } : { name: it.base.name, label: nv.trim() });
      it.title = it.title_en = r.label;
      drawGallery(); libText(); setStatus(TX(`Renamed to "${r.label}".`, `已改名为“${r.label}”。`));
    } catch (e) { setStatus(e.message, true); }
  }
  async function restoreBuiltins() {
    try { await post("/restore_builtins", {}); await refreshGallery(); } catch (e) { setStatus(e.message, true); }
  }
  async function loadGallery(force) {
    const mine = usePic.checked && !!face;
    const key = mine ? JSON.stringify(face) : "default";
    if (!force && galItems.length && galFace === key) return;
    const r = await post("/library", { image: face, use_picture: mine });
    galItems = r.items; galHidden = r.hidden || 0; galFace = key; libText();
  }
  async function refreshGallery() {
    if (usePic.checked && !face) { usePic.checked = false; setStatus(TX("Load Image first to use your picture.", "要用自己的图片，请先加载图片。"), true); }
    // drawing on the user's picture needs the GPU: if a job is running it waits behind it, so say so
    let busy = false;
    if (usePic.checked) {
      // a server too busy to answer within 3 s counts as busy
      busy = true;
      try {
        const q = await Promise.race([api.fetchApi("/queue").then(r => r.json()), new Promise((_, no) => setTimeout(() => no(), 3000))]);
        busy = (q.queue_running || []).length + (q.queue_pending || []).length > 0;
      } catch (e) { }
    }
    const msg = !usePic.checked ? TX("Loading…", "载入中…")
      : busy ? TX("Queued: the graphics card is busy with another job. The thumbnails are drawn when it finishes.", "正在排队：显卡正在跑别的任务，等它结束后才会画缩略图。")
      : TX("Drawing the thumbnails on your picture…", "正在用你的图片画缩略图…");
    galGrid.innerHTML = ""; galGrid.append(el("div", { style: "color:#8fb3c9" }, msg));
    usePicBtn.disabled = true; usePic.disabled = true;
    try { await loadGallery(true); drawGallery(); } catch (e) { setStatus(e.message, true); }
    finally { usePicBtn.disabled = false; usePic.disabled = !face; }
  }
  async function openGallery() {
    gal.style.display = "flex"; usePic.disabled = !face; if (!face) usePic.checked = false;
    if (!galItems.length) { galGrid.innerHTML = ""; galGrid.append(el("div", { style: "color:#8fb3c9" }, TX("Loading…", "载入中…"))); }
    try { await loadGallery(); drawGallery(); } catch (e) { setStatus(e.message, true); gal.style.display = "none"; }
  }
  async function pick(it) {
    push();
    if (it.studio) {           // a studio entry: load its whole state to keep editing it
      const r = await post("/load", { name: it.base.name });
      state = Object.assign(DEFAULT(), r.state); nameIn.value = it.base.name; labelIn.value = r.label; descIn.value = r.description; syncSliders();
    } else state.base = it.base;
    gal.style.display = "none";
    for (const [n, b] of Object.entries(tabs)) b.classList.toggle("on", n === "library");
    panels.video.style.display = "none";
    libText(); frame = null; refresh();
  }
  galSearch.addEventListener("input", () => drawGallery());
  function fillLibrary() { libText(); }

  // ---------- video
  async function loadVideo(rel) {
    if (!rel) return;
    video = parseAnnotated(rel); mark = { start: null, end: null }; markLabel.textContent = "";
    vidName.textContent = video.filename; vidName.title = rel;
    try {
      vinfo = await post("/video/info", { video: video });
      vt.max = Math.max(0.01, vinfo.duration - 1 / vinfo.fps); vt.step = 1 / vinfo.fps; vt.value = 0;
      srcPane.style.display = ""; vbar.style.display = "flex"; scrub();
    } catch (e) { setStatus(e.message, true); }
  }
  let vbusy = false, vpending = false;
  async function scrub() {
    if (!video) return;
    vtLabel.textContent = (+vt.value).toFixed(2) + "s";
    if (vbusy) { vpending = true; return; }
    vbusy = true;
    try {
      const d = await post("/video/frame", { video, image: face, t: +vt.value, ref_t: mark.start ?? 0, head_motion: hm.checked, state });
      srcImg.src = d.source;
      if (d.face) faceImg.src = d.face;
      setStatus(d.face_error || (mark.start == null ? TX("Set a start mark at a calm moment before the expression.", "先在表情开始前的平静处设起点。") : ""), !!d.face_error);
    } catch (e) { setStatus(e.message, true); }
    vbusy = false;
    if (vpending) { vpending = false; scrub(); }
  }
  function setMark(which) {
    mark[which] = +vt.value;
    const s = mark.start, e = mark.end;
    let t = `start ${s == null ? "—" : s.toFixed(2) + "s"} · end ${e == null ? "—" : e.toFixed(2) + "s"}`;
    if (s != null && e != null) t += ` · ${(e - s).toFixed(2)}s` + (e - s > meta.max_segment ? ` (max ${meta.max_segment}s!)` : "");
    markLabel.textContent = t; if (which === "start") scrub();
  }
  function closeVideo() { video = null; vbar.style.display = "none"; srcPane.style.display = "none"; vidName.textContent = ""; frame = null; refresh(); }
  function showSeg() {
    const b = state.base;
    segInfo.textContent = b.kind === "video" ? TX(`Using ${b.src?.video || "a video"}  ${(+b.src?.start || 0).toFixed(2)}s – ${(+b.src?.end || 0).toFixed(2)}s (${b.frames.length} frames)`, `正在用这一段：${b.src?.video || "视频"}  ${(+b.src?.start || 0).toFixed(2)} 秒 – ${(+b.src?.end || 0).toFixed(2)} 秒（${b.frames.length} 帧）`) : TX("No segment taken yet", "还没取片段");
  }
  useSeg.addEventListener("click", async () => {
    if (mark.start == null || mark.end == null) { setStatus(TX("Set a start and an end first.", "先设起点和终点。"), true); return; }
    useSeg.disabled = true; setStatus(TX("Reading the expression from the segment…", "正在读取表情…"));
    try {
      const d = await post("/video/capture", { video, start: mark.start, end: mark.end, head_motion: hm.checked });
      push();
      state.base = { kind: "video", frames: d.frames, src: { video: `${video.subfolder ? video.subfolder + "/" : ""}${video.filename}`, start: mark.start, end: mark.end } };
      state.head_motion = hm.checked;
      setStatus(TX(`Segment taken: ${d.frames.length} frames at 24 fps. Fine-tune it with the sliders, Play to check.`, `已取这一段，可以用滑块微调，点播放查看。`));
      if (d.warning) warn(TX(d.warning.en, d.warning.zh));
      for (const [n, b] of Object.entries(tabs)) b.classList.remove("on");
      panels.video.style.display = ""; libText(); showSeg();
      frame = null; refresh();
    } catch (e) { setStatus(e.message, true); }
    useSeg.disabled = false;
  });
  vidUp.addEventListener("change", async () => {
    const f = vidUp.files[0]; if (!f) return;
    try {
      setStatus(TX("Uploading…", "上传中"));
      const u = await upload(f, "H3MD_expression_videos");
      const rel = (u.subfolder ? u.subfolder + "/" : "") + u.filename; loadVideo(rel); setStatus("");
    } catch (e) { setStatus(e.message, true); }
  });
  vt.addEventListener("input", () => { stop(); scrub(); });
  hm.addEventListener("change", () => scrub());

  function showTab(k) {
    for (const [n, b] of Object.entries(tabs)) b.classList.toggle("on", n === k);
    panels.none.style.display = k === "none" ? "" : "none";
    panels.library.style.display = k === "library" ? "" : "none";
    panels.video.style.display = "none";
    srcPane.style.display = video ? "" : "none";
    if (k === "none" && state.base.kind !== "none") { push(); state.base = { kind: "none" }; frame = null; refresh(); }
    if (k === "library") openGallery();
  }

  // ---------- timeline
  tl.addEventListener("input", () => { stop(); refresh(+tl.value); });
  peakBtn.addEventListener("click", () => { stop(); frame = null; refresh(); });
  async function exportImage() {
    if (!face) { setStatus(TX("Load the picture first.", "请先加载图片。"), true); return; }
    stop(); exportBtn.disabled = true; setStatus(TX("Saving the picture…", "正在导出图片…"));
    try {
      const r = await post("/export_image", { image: face, state, frame: +tl.value, face_only: faceOnly.checked, name: nameIn.value.trim() || labelIn.value.trim() });
      lastFolder = r.folder;
      setStatus(TX(`Saved ${r.filename} (frame ${r.frame + 1}, ${r.size[0]}x${r.size[1]}) in the output folder.`,
                   `已导出 ${r.filename}（第 ${r.frame + 1} 帧，${r.size[0]}x${r.size[1]}），在 output 文件夹里。`));
    } catch (e) { setStatus(e.message, true); }
    exportBtn.disabled = false;
  }
  playBtn.addEventListener("click", () => play());
  const baseName = x => x ? x.filename : "";
  function setImgName() { imgName.textContent = baseName(face); imgName.title = face ? (face.subfolder ? face.subfolder + "/" : "") + face.filename : ""; }
  async function loadFace(force) {
    if (!face) { refresh(); return; }
    setStatus(TX("Loading the face…", "正在读取脸部（新图片约十几秒）"));
    const slow = setTimeout(() => setStatus(TX("Still loading after 30 s — the GPU may be busy with another job. Press Reload to try again.", "30 秒还没好：显卡可能在忙别的任务，可以点 Reload 重新载入。"), true), 30000);
    try { await post("/face", { image: face }); setStatus(""); frame = null; await refresh(); }
    catch (e) { setStatus(e.message, true); }
    finally { clearTimeout(slow); }
  }
  faceUp.addEventListener("change", async () => {
    const f = faceUp.files[0]; if (!f) return;
    try {
      face = await upload(f, "H3MD_expression_uploads"); state.image = face; galItems = [];
      setImgName(); pathRow.style.display = "none"; loadFace();
    } catch (e) { setStatus(e.message, true); }
  });

  function syncAll() {
    syncSliders(); hm.checked = state.head_motion !== false; fillLibrary();
    const k = state.base.kind === "video" ? "video" : state.base.kind === "none" ? "none" : "library";
    for (const [n, b] of Object.entries(tabs)) b.classList.toggle("on", n === k);
    panels.video.style.display = k === "video" ? "" : "none";
    showSeg(); buttons();
  }

  // ---------- start
  dlg.showModal();
  setStatus(TX("Loading…", "载入中"));
  (async () => {
    try {
      meta = await (await api.fetchApi(R + "/meta")).json();
      buildSliders(); syncAll();
      labelIn.value = state.label || ""; descIn.value = state.description || ""; if (savedName) nameIn.value = savedName;
      if (state.base.kind === "video" && state.base.src?.video) {
        await loadVideo(state.base.src.video);
        mark = { start: state.base.src.start, end: state.base.src.end }; setMark("end");
      }
      setImgName();
      await loadFace();
      try { await loadGallery(); } catch (e) { /* the label can wait */ }
    } catch (e) { setStatus(e.message, true); }
  })();
}

app.registerExtension({
  name: "H3MD.ExpressionStudio",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = created?.apply(this, arguments);
      const btn = this.addWidget("button", TX("Open Expression Studio", "打开表情工作台"), null, () => openStudio(this));
      btn.serialize = false;
      const w = this.widgets.find(x => x.name === "studio");
      if (w?.inputEl) { w.inputEl.readOnly = true; w.inputEl.style.opacity = 0.55; w.inputEl.rows = 2; }
      return r;
    };
  },
});
