# ComfyUI – Load & Resize Image + Filename

A lightweight **ComfyUI custom node** that extends the well-known
[KJNodes `LoadAndResizeImage`](https://github.com/kijai/ComfyUI-KJNodes) with an
additional **`filename` STRING output** so you can feed the loaded file's name
directly into downstream nodes (e.g. save nodes, text nodes, prompt builders).

---

## Features

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

## Installation

### Via ComfyUI Manager (recommended)
Search for **"Load & Resize Image + Filename"** in ComfyUI Manager.

### Manual
```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Slartibart23/ComfyUI-LoadResizeImageWithFilename
```
Restart ComfyUI – no extra dependencies required beyond what ComfyUI already ships.

---

## Requirements

- Python **≥ 3.9** (tested on 3.13)
- ComfyUI (any recent version)
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
- Filename output extension by **Slartibart23**

---

## License

MIT — see [LICENSE](LICENSE).
