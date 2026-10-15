// Crop editor for "Load & Resize Image + Filename (Series/Crop)":
// shows the image that will be loaded and lets you draw a crop rectangle or
// paint a freehand shape, stored as JSON (relative 0..1 coordinates) in the
// hidden "crop_data" widget, which the Python node reads. In crop_mode "mask"
// it shows the mask painted in ComfyUI's MaskEditor instead.

const { app } = window.comfyAPI.app;
const { api } = window.comfyAPI.api;

const NODE_NAME = "LoadAndResizeImageWithFilenameSeriesCrop";
const HANDLE = 7; // handle half-size in CSS px
const FILL_CSS = {
  yellow: "#ffff00", red: "#ff0000", green: "#00ff00",
  blue: "#0000ff", white: "#ffffff", black: "#000000",
};

function parseData(text) {
  try {
    const d = JSON.parse(text || "{}");
    return { rect: Array.isArray(d.rect) ? d.rect : null, strokes: Array.isArray(d.strokes) ? d.strokes : [] };
  } catch {
    return { rect: null, strokes: [] };
  }
}

function clamp01(v) {
  return Math.min(1, Math.max(0, v));
}

function el(tag, css, text) {
  const e = document.createElement(tag);
  if (css) e.style.cssText = css;
  if (text != null) e.textContent = text;
  return e;
}

// "sub/name.png [input]" -> /view URL; channel "rgb" = without transparency, "a" = transparency only
function viewUrl(value, channel) {
  let name = value, type = "input";
  const m = /^(.*) \[(input|output|temp)\]$/.exec(value);
  if (m) { name = m[1]; type = m[2]; }
  const slash = name.lastIndexOf("/");
  const subfolder = slash >= 0 ? name.slice(0, slash) : "";
  const filename = slash >= 0 ? name.slice(slash + 1) : name;
  const ch = channel ? `&channel=${channel}` : "";
  return api.apiURL(`/view?filename=${encodeURIComponent(filename)}&type=${type}&subfolder=${encodeURIComponent(subfolder)}${ch}`);
}

// JPEGs carry no transparency but may carry EXIF rotation, which /view?channel drops
const isJpeg = (value) => /\.jpe?g( \[\w+\])?$/i.test(value || "");

async function fetchImage(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    let err = `HTTP ${res.status}`;
    try { err = (await res.json()).error || err; } catch {}
    throw new Error(err);
  }
  const blob = await res.blob();
  const im = new Image();
  im.src = URL.createObjectURL(blob);
  try {
    await im.decode();
  } finally {
    URL.revokeObjectURL(im.src);
  }
  return { im, headers: res.headers };
}

app.registerExtension({
  name: "Slartibart23.LoadResizeImageWithFilename.CropEditor",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_NAME) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      setupEditor(this);
      return r;
    };
  },
});

function setupEditor(node) {
  const W = (name) => node.widgets?.find((w) => w.name === name);
  const dataWidget = W("crop_data");
  if (!dataWidget) return;
  dataWidget.hidden = true;

  // ---------------------------------------------------------------- DOM
  const wrapper = el("div", "display:flex;flex-direction:column;gap:4px;width:100%;height:100%;box-sizing:border-box;overflow:hidden;");
  const bar = el("div", "display:flex;flex-wrap:wrap;align-items:center;gap:4px;font:12px sans-serif;color:var(--input-text,#ddd);min-height:22px;");
  const info = el("div", "font:11px sans-serif;color:var(--descrip-text,#999);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;");
  const canvasBox = el("div", "position:relative;flex:1 1 auto;min-height:80px;");
  const canvas = el("canvas", "position:absolute;inset:0;width:100%;height:100%;touch-action:none;");
  canvasBox.appendChild(canvas);
  wrapper.append(bar, info, canvasBox);

  const btnCss = "padding:1px 7px;border:1px solid #555;border-radius:4px;background:#333;color:#ddd;cursor:pointer;font:12px sans-serif;";
  const mkBtn = (label, title, onClick) => {
    const b = el("button", btnCss, label);
    b.title = title;
    b.addEventListener("pointerdown", (e) => e.stopPropagation());
    b.addEventListener("click", (e) => { e.stopPropagation(); onClick(); });
    return b;
  };

  const tools = { brush: null, lasso: null, erase: null };
  let tool = node.properties?.lrifTool || "brush";
  let brushPx = node.properties?.lrifBrush || 20;

  const toolButtons = el("span", "display:inline-flex;gap:4px;align-items:center;");
  tools.brush = mkBtn("Brush", "Paint the area to keep", () => setTool("brush"));
  tools.lasso = mkBtn("Lasso", "Draw an outline, it is filled when you release", () => setTool("lasso"));
  tools.erase = mkBtn("Eraser", "Remove painted area", () => setTool("erase"));
  const sizeInput = el("input", "width:70px;");
  Object.assign(sizeInput, { type: "range", min: 2, max: 150, value: brushPx, title: "Brush size" });
  sizeInput.addEventListener("pointerdown", (e) => e.stopPropagation());
  sizeInput.addEventListener("input", () => {
    brushPx = Number(sizeInput.value);
    node.properties.lrifBrush = brushPx;
    draw();
  });
  const undoBtn = mkBtn("Undo", "Undo last stroke", () => {
    data.strokes.pop();
    save();
  });
  toolButtons.append(tools.brush, tools.lasso, tools.erase, sizeInput, undoBtn);
  const clearBtn = mkBtn("Clear", "Remove the rectangle / shape", () => {
    if (mode() === "rectangle") data.rect = null;
    else data.strokes = [];
    save();
  });
  const modeHint = el("span", "font:11px sans-serif;color:var(--descrip-text,#999);");
  bar.append(toolButtons, clearBtn, modeHint);

  function setTool(t) {
    tool = t;
    node.properties.lrifTool = t;
    draw();
  }

  node.addDOMWidget("crop_editor", "LRIFCropEditor", wrapper, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => 220,
  });
  setTimeout(() => {
    if (node.size[0] < 360 || node.size[1] < 620) {
      node.setSize([Math.max(node.size[0], 360), Math.max(node.size[1], 620)]);
    }
  }, 0);

  // -------------------------------------------------------------- state
  let data = parseData(dataWidget.value);
  let img = null;          // HTMLImageElement of the image that will be loaded
  let editorMask = null;   // MaskEditor transparency of the 'image' file (crop_mode mask)
  let imgKey = "", maskKey = "";
  let loadToken = 0, maskToken = 0;
  let message = "";        // shown instead of the image
  let drag = null;         // current pointer interaction
  let hover = null;        // last pointer position (CSS px) for the brush cursor

  const mode = () => W("crop_mode")?.value || "none";

  function save() {
    const clean = {};
    if (data.rect) clean.rect = data.rect.map((v) => Math.round(v * 1e5) / 1e5);
    if (data.strokes.length) clean.strokes = data.strokes;
    dataWidget.value = Object.keys(clean).length ? JSON.stringify(clean) : "";
    lastDataValue = dataWidget.value;
    draw();
    node.setDirtyCanvas?.(true, true);
  }

  // picks up values set by loading a workflow / undo
  let lastDataValue = dataWidget.value;
  function syncFromWidget() {
    if (dataWidget.value !== lastDataValue) {
      lastDataValue = dataWidget.value;
      if (!drag) data = parseData(dataWidget.value);
      return true;
    }
    return false;
  }

  // -------------------------------------------------------- image source
  function folderLinked() {
    const input = node.inputs?.find((i) => i.name === "folder_path");
    return input?.link != null;
  }

  function wantedSource() {
    if (W("source")?.value === "folder") {
      if (folderLinked()) return { key: "linked", message: "No preview: folder_path comes from a link" };
      const folder = (W("folder_path")?.value || "").trim();
      if (!folder) return { key: "nofolder", message: "Enter a folder_path" };
      const index = W("index")?.value ?? 0;
      const url = api.apiURL(`/lrif/folder_image?folder=${encodeURIComponent(folder)}&index=${index}`);
      return { key: `folder|${folder}|${index}`, url, folder: true };
    }
    const value = W("image")?.value;
    if (!value) return { key: "none", message: "No image selected" };
    return { key: `file|${value}`, url: viewUrl(value, isJpeg(value) ? null : "rgb"), label: value };
  }

  async function refreshImage(force = false) {
    const want = wantedSource();
    if (!force && want.key === imgKey) return;
    imgKey = want.key;
    const token = ++loadToken;
    if (want.message) {
      img = null;
      message = want.message;
      info.textContent = "";
      draw();
      return;
    }
    try {
      const { im, headers } = await fetchImage(want.url);
      if (token !== loadToken) return;
      img = im;
      message = "";
      if (want.folder) {
        const name = decodeURIComponent(headers.get("X-LRIF-Filename") || "");
        const idx = Number(headers.get("X-LRIF-Index"));
        const count = Number(headers.get("X-LRIF-Count"));
        info.textContent = `Next: ${name}  (${idx + 1} / ${count})  ${im.naturalWidth}×${im.naturalHeight}`;
      } else {
        info.textContent = `${want.label}  ${im.naturalWidth}×${im.naturalHeight}`;
      }
    } catch (e) {
      if (token !== loadToken) return;
      img = null;
      message = String(e.message || e);
      info.textContent = "";
    }
    draw();
  }

  // the MaskEditor stores its mask as transparency of the file picked in 'image'
  async function refreshMask() {
    const value = W("image")?.value;
    const key = mode() === "mask" && value && !isJpeg(value) ? value : "";
    if (key === maskKey) return;
    maskKey = key;
    const token = ++maskToken;
    editorMask = null;
    if (key) {
      try {
        const { im } = await fetchImage(viewUrl(value, "a"));
        if (token === maskToken) editorMask = im;
      } catch {
        // no mask to show; the node then uses the full image
      }
    }
    draw();
  }

  // ---------------------------------------------------------- geometry
  // where the image sits inside the canvas (CSS px)
  function imageBox() {
    const cw = canvas.clientWidth, ch = canvas.clientHeight;
    if (!img || !cw || !ch) return null;
    const s = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
    const w = img.naturalWidth * s, h = img.naturalHeight * s;
    return { x: (cw - w) / 2, y: (ch - h) / 2, w, h };
  }

  function toRel(e, box) {
    const r = canvas.getBoundingClientRect();
    // the canvas may be scaled by the graph zoom: map client px -> CSS px
    const sx = canvas.clientWidth / r.width, sy = canvas.clientHeight / r.height;
    const x = (e.clientX - r.left) * sx, y = (e.clientY - r.top) * sy;
    return { x, y, rx: (x - box.x) / box.w, ry: (y - box.y) / box.h };
  }

  function rectHandles(box) {
    const [x, y, w, h] = data.rect;
    const L = box.x + x * box.w, T = box.y + y * box.h, R = L + w * box.w, B = T + h * box.h;
    const mx = (L + R) / 2, my = (T + B) / 2;
    return { nw: [L, T], n: [mx, T], ne: [R, T], e: [R, my], se: [R, B], s: [mx, B], sw: [L, B], w: [L, my], L, T, R, B };
  }

  function hitRect(p, box) {
    if (!data.rect) return null;
    const hs = rectHandles(box);
    for (const k of ["nw", "ne", "se", "sw", "n", "e", "s", "w"]) {
      const [hx, hy] = hs[k];
      if (Math.abs(p.x - hx) <= HANDLE + 3 && Math.abs(p.y - hy) <= HANDLE + 3) return k;
    }
    if (p.x > hs.L && p.x < hs.R && p.y > hs.T && p.y < hs.B) return "move";
    return null;
  }

  const CURSORS = { nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize", n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize", move: "move" };

  // ------------------------------------------------------------ drawing
  // paints the freehand strokes into ctx, scaled to box (shape = opaque)
  function paintStrokes(ctx, box, strokes) {
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const st of strokes) {
      const pts = st.p || [];
      if (!pts.length) continue;
      ctx.globalCompositeOperation = st.t === "erase" ? "destination-out" : "source-over";
      ctx.fillStyle = ctx.strokeStyle = "#fff";
      if (st.t === "lasso") {
        if (pts.length < 3) continue;
        ctx.beginPath();
        ctx.moveTo(box.x + pts[0][0] * box.w, box.y + pts[0][1] * box.h);
        for (const q of pts.slice(1)) ctx.lineTo(box.x + q[0] * box.w, box.y + q[1] * box.h);
        ctx.closePath();
        ctx.fill();
        continue;
      }
      const lw = Math.max(1, (st.s || 0.02) * box.w);
      ctx.lineWidth = lw;
      ctx.beginPath();
      ctx.moveTo(box.x + pts[0][0] * box.w, box.y + pts[0][1] * box.h);
      if (pts.length === 1) ctx.lineTo(box.x + pts[0][0] * box.w + 0.01, box.y + pts[0][1] * box.h);
      for (const q of pts.slice(1)) ctx.lineTo(box.x + q[0] * box.w, box.y + q[1] * box.h);
      ctx.stroke();
    }
    ctx.globalCompositeOperation = "source-over";
  }

  // MaskEditor mask: painted = transparent in the alpha image -> opaque here
  function paintEditorMask(ctx, box) {
    ctx.fillStyle = "#fff";
    ctx.fillRect(box.x, box.y, box.w, box.h);
    ctx.globalCompositeOperation = "destination-out";
    ctx.drawImage(editorMask, box.x, box.y, box.w, box.h);
    ctx.globalCompositeOperation = "source-over";
  }

  const shapeCanvas = document.createElement("canvas");
  const tintCanvas = document.createElement("canvas");

  function draw() {
    const dpr = window.devicePixelRatio || 1;
    const cw = canvas.clientWidth, ch = canvas.clientHeight;
    if (!cw || !ch) return;
    if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) {
      canvas.width = Math.round(cw * dpr);
      canvas.height = Math.round(ch * dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cw, ch);

    const m = mode();
    toolButtons.style.display = m === "freehand" ? "inline-flex" : "none";
    clearBtn.style.display = m === "rectangle" || m === "freehand" ? "" : "none";
    modeHint.textContent = {
      none: "crop_mode = none: no crop",
      rectangle: "Drag to draw, drag edges/corners to adjust",
      freehand: "",
      mask: editorMask ? "Mask from right-click → Open in MaskEditor"
        : "Paint a mask: right-click → Open in MaskEditor",
    }[m] ?? "";
    for (const [k, b] of Object.entries(tools)) b.style.background = k === tool ? "#2a6db0" : "#333";

    const box = imageBox();
    if (!box) {
      ctx.fillStyle = "#888";
      ctx.font = "12px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(message || "Loading…", cw / 2, ch / 2);
      return;
    }
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(img, box.x, box.y, box.w, box.h);

    if (m === "rectangle" && data.rect) {
      const hs = rectHandles(box);
      ctx.fillStyle = "rgba(0,0,0,0.55)";
      ctx.beginPath();
      ctx.rect(box.x, box.y, box.w, box.h);
      ctx.rect(hs.L, hs.T, hs.R - hs.L, hs.B - hs.T);
      ctx.fill("evenodd");
      ctx.strokeStyle = "#4af";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(hs.L, hs.T, hs.R - hs.L, hs.B - hs.T);
      ctx.fillStyle = "#4af";
      for (const k of ["nw", "n", "ne", "e", "se", "s", "sw", "w"]) {
        const [hx, hy] = hs[k];
        ctx.fillRect(hx - HANDLE / 2 - 1, hy - HANDLE / 2 - 1, HANDLE + 2, HANDLE + 2);
      }
      const pw = Math.round(data.rect[2] * img.naturalWidth), ph = Math.round(data.rect[3] * img.naturalHeight);
      label(ctx, `${pw}×${ph}`, hs.L + 4, hs.T + 4);
    }

    const shaped = m === "freehand" || (m === "mask" && editorMask);
    if (shaped) {
      for (const c of [shapeCanvas, tintCanvas]) { c.width = canvas.width; c.height = canvas.height; }
      const sctx = shapeCanvas.getContext("2d");
      sctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (m === "mask") paintEditorMask(sctx, box);
      else paintStrokes(sctx, box, drag?.stroke ? [...data.strokes, drag.stroke] : data.strokes);

      // everything outside the shape gets the fill colour
      const fill = FILL_CSS[W("fill_color")?.value] || FILL_CSS.yellow;
      const tctx = tintCanvas.getContext("2d");
      tctx.globalAlpha = 0.65;
      tctx.fillStyle = fill;
      tctx.fillRect(box.x * dpr, box.y * dpr, box.w * dpr, box.h * dpr);
      tctx.globalAlpha = 1;
      tctx.globalCompositeOperation = "destination-out";
      tctx.drawImage(shapeCanvas, 0, 0);
      tctx.globalCompositeOperation = "source-over";

      // bounding box = what will be passed on; nothing painted = full image
      const bb = drag ? null : shapeBounds(sctx, box, dpr);
      if (bb || drag) {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.drawImage(tintCanvas, 0, 0);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
      if (bb) {
        ctx.strokeStyle = "#4af";
        ctx.setLineDash([5, 4]);
        ctx.lineWidth = 1.5;
        ctx.strokeRect(bb.x, bb.y, bb.w, bb.h);
        ctx.setLineDash([]);
        const pw = Math.round((bb.w / box.w) * img.naturalWidth), ph = Math.round((bb.h / box.h) * img.naturalHeight);
        label(ctx, `${pw}×${ph}`, bb.x + 4, bb.y + 4);
      }
    }

    if (m === "freehand") {
      // the lasso outline while drawing
      if (drag?.stroke?.t === "lasso" && drag.stroke.p.length > 1) {
        const pts = drag.stroke.p;
        ctx.strokeStyle = "#fff";
        ctx.setLineDash([4, 3]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(box.x + pts[0][0] * box.w, box.y + pts[0][1] * box.h);
        for (const q of pts.slice(1)) ctx.lineTo(box.x + q[0] * box.w, box.y + q[1] * box.h);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      if (hover && tool !== "lasso") {
        ctx.strokeStyle = tool === "erase" ? "#f66" : "#fff";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(hover.x, hover.y, brushPx / 2, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
  }

  function label(ctx, text, x, y) {
    ctx.font = "11px sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    const w = ctx.measureText(text).width;
    ctx.fillStyle = "rgba(0,0,0,0.65)";
    ctx.fillRect(x - 2, y - 1, w + 4, 14);
    ctx.fillStyle = "#fff";
    ctx.fillText(text, x, y);
  }

  function shapeBounds(sctx, box, dpr) {
    const x0 = Math.floor(box.x * dpr), y0 = Math.floor(box.y * dpr);
    const w = Math.ceil(box.w * dpr), h = Math.ceil(box.h * dpr);
    if (w < 1 || h < 1) return null;
    const px = sctx.getImageData(x0, y0, w, h).data;
    let minX = w, minY = h, maxX = -1, maxY = -1;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        if (px[(y * w + x) * 4 + 3] > 127) {
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }
    if (maxX < 0) return null;
    return { x: (x0 + minX) / dpr, y: (y0 + minY) / dpr, w: (maxX - minX + 1) / dpr, h: (maxY - minY + 1) / dpr };
  }

  // ------------------------------------------------------------ pointer
  canvas.addEventListener("pointerdown", (e) => {
    const m = mode();
    const box = imageBox();
    if ((m !== "rectangle" && m !== "freehand") || !box || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    canvas.setPointerCapture(e.pointerId);
    const p = toRel(e, box);

    if (m === "rectangle") {
      const hit = hitRect(p, box);
      if (hit) {
        drag = { type: hit, start: p, rect: [...data.rect] };
      } else {
        const rx = clamp01(p.rx), ry = clamp01(p.ry);
        data.rect = [rx, ry, 0, 0];
        drag = { type: "se", start: { ...p, rx, ry }, rect: [rx, ry, 0, 0] };
      }
    } else {
      const pt = [clamp01(p.rx), clamp01(p.ry)];
      drag = { type: "stroke", stroke: { t: tool, s: brushPx / box.w, p: [pt] } };
      if (tool === "lasso") delete drag.stroke.s;
    }
    draw();
  });

  canvas.addEventListener("pointermove", (e) => {
    const box = imageBox();
    if (!box) return;
    const p = toRel(e, box);
    hover = { x: p.x, y: p.y };
    const m = mode();

    if (!drag) {
      if (m === "rectangle") canvas.style.cursor = CURSORS[hitRect(p, box)] || "crosshair";
      else canvas.style.cursor = m === "freehand" ? (tool === "lasso" ? "crosshair" : "none") : "default";
      if (m === "freehand") draw();
      return;
    }
    e.preventDefault();
    e.stopPropagation();

    if (drag.type === "stroke") {
      const pts = drag.stroke.p;
      const pt = [clamp01(p.rx), clamp01(p.ry)];
      const last = pts[pts.length - 1];
      // skip points closer than ~1.5 CSS px
      if (Math.hypot((pt[0] - last[0]) * box.w, (pt[1] - last[1]) * box.h) >= 1.5) pts.push(pt);
      draw();
      return;
    }

    // rectangle: move or resize from the rect at drag start
    let [x, y, w, h] = drag.rect;
    const dx = p.rx - drag.start.rx, dy = p.ry - drag.start.ry;
    if (drag.type === "move") {
      x = Math.min(Math.max(x + dx, 0), 1 - w);
      y = Math.min(Math.max(y + dy, 0), 1 - h);
    } else {
      let L = x, T = y, R = x + w, B = y + h;
      if (drag.type.includes("w")) L = clamp01(L + dx);
      if (drag.type.includes("e")) R = clamp01(R + dx);
      if (drag.type.includes("n")) T = clamp01(T + dy);
      if (drag.type.includes("s")) B = clamp01(B + dy);
      x = Math.min(L, R); y = Math.min(T, B);
      w = Math.abs(R - L); h = Math.abs(B - T);
    }
    data.rect = [x, y, w, h];
    draw();
  });

  const endDrag = (e) => {
    if (!drag) return;
    e.stopPropagation();
    if (drag.type === "stroke") {
      const st = drag.stroke;
      if (st.t !== "lasso" || st.p.length >= 3) {
        st.p = st.p.map(([x, y]) => [Math.round(x * 1e4) / 1e4, Math.round(y * 1e4) / 1e4]);
        if (st.s) st.s = Math.round(st.s * 1e4) / 1e4;
        data.strokes.push(st);
      }
    } else if (data.rect && img && (data.rect[2] * img.naturalWidth < 2 || data.rect[3] * img.naturalHeight < 2)) {
      data.rect = drag.type === "se" && drag.rect[2] === 0 ? null : drag.rect;
    }
    drag = null;
    save();
  };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener("pointerleave", () => { hover = null; if (!drag) draw(); });

  // ------------------------------------------------------------ updates
  new ResizeObserver(() => draw()).observe(canvasBox);

  // The editor already shows the image. ComfyUI only creates its own preview
  // widget when none with that name exists, so a hidden placeholder keeps it
  // away (node.imgs stays intact, "Open in MaskEditor" keeps working).
  // If ComfyUI removed the placeholder and added the real one, hide that.
  const PREVIEW = "$$canvas-image-preview";
  function hideDefaultPreview() {
    const pw = node.widgets?.find((w) => w.name === PREVIEW);
    if (!pw) {
      node.addCustomWidget({
        name: PREVIEW, type: "lrif_hidden_preview", value: "", hidden: true,
        serialize: false, options: { serialize: false },
        draw() {}, computeSize: () => [0, -4],
      });
    } else if (!pw.hidden) {
      pw.hidden = true;
      pw.computeSize = () => [0, -4];
      node.setDirtyCanvas?.(true, true);
    }
  }
  hideDefaultPreview();

  // widget values change from many places (queue increment, workflow load,
  // MaskEditor, links); a cheap poll keeps the preview in sync with all of them
  let lastLook = "";
  const timer = setInterval(() => {
    if (!node.graph) return;
    hideDefaultPreview();
    const changed = syncFromWidget();
    refreshImage();
    refreshMask();
    const look = `${mode()}|${W("fill_color")?.value}`;
    if (changed || look !== lastLook) {
      lastLook = look;
      draw();
    }
  }, 300);

  const onConfigure = node.onConfigure;
  node.onConfigure = function () {
    const r = onConfigure?.apply(this, arguments);
    data = parseData(dataWidget.value);
    lastDataValue = dataWidget.value;
    return r;
  };

  const onRemoved = node.onRemoved;
  node.onRemoved = function () {
    clearInterval(timer);
    return onRemoved?.apply(this, arguments);
  };

  setTool(tool);
  refreshImage(true);
}
