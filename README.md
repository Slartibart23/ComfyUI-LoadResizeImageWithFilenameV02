# ComfyUI – Load & Resize Image + Filename

A **ComfyUI custom node** that extends the well-known
[KJNodes `LoadAndResizeImage`](https://github.com/kijai/ComfyUI-KJNodes) with:

- a **`filename` STRING output** so you can feed the loaded file's name
  directly into downstream nodes (e.g. save nodes, text nodes, prompt builders)
- a **folder series**: every queued run loads the next image, stops after the last one
- a **choice of mask**: the standard MaskEditor mask, or a rectangle / freehand
  shape drawn right in the node

The node never crops by itself — connect `image` and `mask` to a mask crop node
such as **Image Crop By Mask** (KJNodes) to cut out the selected area.

Workflows saved with version 1 keep working: their settings are kept and the
new inputs start with defaults that behave like version 1.

---

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| `image` | `IMAGE` | Loaded (and optionally resized) image as a float32 tensor (B, H, W, 3); with `freehand` filled outside the shape |
| `mask` | `MASK` | (B, H, W) mask chosen by `mask_source` (1 = selected) |
| `width` | `INT` | Final image width (after optional resize) |
| `height` | `INT` | Final image height (after optional resize) |
| `filename` | `STRING` | File stem without extension (e.g. `my_photo`) |
| `index` | `INT` | Position of the loaded file in the folder (0 in single image mode) |
| `file_count` | `INT` | Number of images in the folder (1 in single image mode) |

## Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `image` | — | File picker (same as standard ComfyUI Load Image) |
| `resize` | `False` | Enable resizing |
| `width` | `512` | Target width |
| `height` | `512` | Target height |
| `keep_proportion` | `False` | Scale uniformly to fit within width × height |
| `divisible_by` | `32` | Round output dimensions to a multiple of this value |
| `upscale_method` | `lanczos` | Interpolation: nearest-exact / bilinear / area / bicubic / lanczos |
| `source` | `single image` | `single image` = the file picked in `image`, `folder` = the file at `index` in `folder_path` |
| `folder_path` | — | Folder with the image series (can also be connected as an input) |
| `index` | `0` | Position in the folder, 0 = first file. *control after generate* is set to `increment` |
| `mask_source` | `MaskEditor` | `MaskEditor`, `rectangle` or `freehand` (see below) |
| `fill_color` | `yellow` | Colour outside the shape for `freehand`: yellow / red / green / blue / white / black |

---

## Folder series

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

---

## Mask and cropping

The node always outputs the **whole image** plus a mask. To cut out the selected
area, connect both to **Image Crop By Mask** (KJNodes) or a similar node:

```
[Load & Resize Image + Filename] --image--> [Image Crop By Mask] --image--> ...
                                 --mask---->
```

`mask_source` decides which mask comes out:

| `mask_source` | `mask` output | `image` output |
|---------------|---------------|----------------|
| `MaskEditor` (default) | the mask painted via right-click on the image → *Open in MaskEditor*, as in version 1 | unchanged |
| `rectangle` | the rectangle drawn in the node | unchanged |
| `freehand` | the shape painted in the node | outside the shape filled with `fill_color` |

**`rectangle`** — drag on the image to draw a rectangle; drag inside it to move
it, drag its edges or corners to resize it.

**`freehand`** — paint the area to keep right in the node:
**Brush** paints, **Eraser** removes, **Lasso** draws an outline that is filled
when you release the mouse; the slider sets the brush size, **Undo** removes the
last stroke, **Clear** removes everything. After Image Crop By Mask you get the
smallest rectangle around the shape with everything outside the shape in `fill_color`.

The preview shows the rectangle / the shape's bounding box with its size in pixels.
If nothing is drawn, the mask covers the whole image, so the crop keeps the full
image instead of failing. With `MaskEditor` an empty mask stays empty, as in
standard ComfyUI (Image Crop By Mask then reports an error).

In a folder series the rectangle and the freehand shape are applied to every
image in the same relative position.

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
- Filename output, folder series and mask editor by **Slartibart23**

---

## License

MIT — see [LICENSE](LICENSE).
