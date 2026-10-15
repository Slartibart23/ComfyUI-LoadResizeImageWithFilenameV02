# ComfyUI – Load & Resize Image + Filename

**ComfyUI custom nodes** that extend the well-known
[KJNodes `LoadAndResizeImage`](https://github.com/kijai/ComfyUI-KJNodes). The pack
contains two nodes:

| Node | What it adds |
|------|--------------|
| **Load & Resize Image + Filename** | a **`filename` STRING output** so you can feed the loaded file's name directly into downstream nodes (e.g. save nodes, text nodes, prompt builders) |
| **Load & Resize Image + Filename (Series/Crop)** | everything above, plus a **folder series** (every queued run loads the next image, stops after the last one) and **cropping**: a rectangle or freehand shape drawn in the node, or the mask painted in ComfyUI's MaskEditor |

The first node is unchanged from version 1, so existing workflows keep working.
Both nodes support ComfyUI's MaskEditor (right-click → *Open in MaskEditor*).

---

## Load & Resize Image + Filename

| Output | Type | Description |
|--------|------|-------------|
| `image` | `IMAGE` | Loaded image as a float32 tensor (B, H, W, 3) |
| `mask` | `MASK` | Alpha channel extracted as a (B, H, W) mask tensor |
| `width` | `INT` | Final image width (after optional resize) |
| `height` | `INT` | Final image height (after optional resize) |
| `filename` | `STRING` | File stem without extension (e.g. `my_photo`) |

**Inputs:**

| Input | Default | Description |
|-------|---------|-------------|
| `image` | — | File picker (same as standard ComfyUI Load Image) |
| `resize` | `False` | Enable resizing |
| `width` | `512` | Target width |
| `height` | `512` | Target height |
| `keep_proportion` | `False` | Scale uniformly to fit within width × height |
| `divisible_by` | `2` | Round output dimensions to a multiple of this value |
| `upscale_method` | `lanczos` | Interpolation: nearest-exact / bilinear / area / bicubic / lanczos |

---

## Load & Resize Image + Filename (Series/Crop)

Same inputs and outputs as above, plus:

| Input | Default | Description |
|-------|---------|-------------|
| `source` | `single image` | `single image` = the file picked in `image`, `folder` = the file at `index` in `folder_path` |
| `folder_path` | — | Folder with the image series (can also be connected as an input) |
| `index` | `0` | Position in the folder, 0 = first file. *control after generate* is set to `increment` |
| `crop_mode` | `none` | `none`, `rectangle`, `freehand` or `mask` (see below) |
| `fill_color` | `yellow` | Colour outside the shape for `freehand` / `mask`: yellow / red / green / blue / white / black |

| Extra output | Type | Description |
|--------------|------|-------------|
| `index` | `INT` | Position of the loaded file in the folder (0 in single image mode) |
| `file_count` | `INT` | Number of images in the folder (1 in single image mode) |

In freehand and mask mode the `mask` output contains the shape (1 = selected).

### Folder series

1. Set `source` to `folder` and enter `folder_path` (e.g. `D:\photos\batch01`).
2. Set `index` to `0`.
3. Queue the workflow N times (e.g. *Run* with a batch count of 10).

Each queued run loads the next file — any file names work (`.jpg`, `.jpeg`,
`.png`, `.webp`, `.bmp`, `.tif`, `.tiff`, `.gif`). Files are sorted by name with
numbers in natural order (`img2` before `img10`). The `filename` output carries
the name of the file that was actually loaded, and the preview in the node shows
the **next** file that will be loaded.

The series **never repeats**: the first run after the last file stops with
*"Series finished"*, and any further queued runs of the same series are removed
from the queue (other queued work is left alone). Set `index` back to `0` to
start again.

### Cropping

The node shows the image that will be loaded. The crop is applied **before** the
optional resize, so `width`/`height` refer to the cropped image when resize is off.

**`rectangle`** — drag on the image to draw a rectangle; drag inside it to move
it, drag its edges or corners to resize it. Only this part of the image is passed on.

**`freehand`** — paint the area to keep right in the node:
**Brush** paints, **Eraser** removes, **Lasso** draws an outline that is filled
when you release the mouse; the slider sets the brush size, **Undo** removes the
last stroke, **Clear** removes everything.

**`mask`** — paint the area to keep in ComfyUI's own MaskEditor
(right-click on the node → *Open in MaskEditor*), then save. The node shows the
mask in its preview.

With `freehand` and `mask` the output is the smallest rectangle around the shape
(shown as a dashed frame with its size); everything inside it but outside the
shape is filled with `fill_color`. If nothing is drawn, the full image is used.

In a folder series the rectangle, the freehand shape and the MaskEditor mask
(painted on the file picked in `image`) are applied to every image in the same
relative position.

---

## Installation

### Via ComfyUI Manager (recommended)
Search for **"Load & Resize Image + Filename"** in ComfyUI Manager.

### Manual
```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Slartibart23/ComfyUI-LoadResizeImageWithFilenameV02
```
Restart ComfyUI – no extra dependencies required beyond what ComfyUI already ships.

---

## Requirements

- Python **≥ 3.9** (tested on 3.12 and 3.13)
- ComfyUI (tested with 0.40 / frontend 1.55)
- `torch`, `Pillow`, `numpy` — all provided by ComfyUI's environment

---

## Usage example

```
[Load & Resize Image + Filename]
       │                   │
    IMAGE                STRING (filename)
       │                   │
  [Your model]     [Save Image KJ]  ← filename_prefix connected here
```

The `filename` output carries only the **stem** (no path, no extension), e.g.:

| Uploaded file | `filename` output |
|---------------|-------------------|
| `portrait_001.png` | `portrait_001` |
| `my photo.jpg` | `my photo` |
| `frame_0042.webp` | `frame_0042` |

---

## Credits

- Node logic based on **KJNodes `LoadAndResizeImage`** by
  [kijai](https://github.com/kijai/ComfyUI-KJNodes) — MIT License
- Filename output, folder series and cropping by **Slartibart23**

---

## License

MIT — see [LICENSE](LICENSE).
