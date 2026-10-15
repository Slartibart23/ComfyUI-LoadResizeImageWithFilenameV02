"""
LoadAndResizeImageWithFilename Node
Based on KJNodes LoadAndResizeImage by kijai (https://github.com/kijai/ComfyUI-KJNodes)
Extended by Slartibart23 with:
  • filename output
  • folder series: every queued run loads the next file, stops at the end
  • crop: rectangle or freehand shape drawn in the node preview, or the mask
    painted in ComfyUI's MaskEditor; the area outside a shape is filled with a colour

Compatible with Python 3.9+
"""

import os
import re
import json
import hashlib
from typing import List, Optional, Tuple

import torch
import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageSequence

import folder_paths
from comfy.utils import common_upscale


NODE_ID = "LoadAndResizeImageWithFilename"

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif")

FILL_COLORS = {
    "yellow": (1.0, 1.0, 0.0),
    "red": (1.0, 0.0, 0.0),
    "green": (0.0, 1.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
    "white": (1.0, 1.0, 1.0),
    "black": (0.0, 0.0, 0.0),
}


# ----------------------------------------------------------------------
# folder series helpers (also used by the web route in __init__.py)
# ----------------------------------------------------------------------

def _natural_key(name: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


def _clean_folder(folder: str) -> str:
    return folder.strip().strip('"')


def list_folder_images(folder: str) -> List[str]:
    """Return the image files in ``folder`` (not recursive), naturally sorted."""
    folder = _clean_folder(folder)
    if not folder or not os.path.isdir(folder):
        raise FileNotFoundError(f"Folder not found: {folder!r}")
    files = [
        f for f in os.listdir(folder)
        if f.lower().endswith(IMAGE_EXTENSIONS) and os.path.isfile(os.path.join(folder, f))
    ]
    if not files:
        raise FileNotFoundError(f"No images ({', '.join(IMAGE_EXTENSIONS)}) in folder: {folder!r}")
    return [os.path.join(folder, f) for f in sorted(files, key=_natural_key)]


class EndOfSeries(Exception):
    pass


def resolve_folder_image(folder: str, index: int) -> Tuple[str, int]:
    """Pick the file for ``index``. Returns (path, file_count); raises EndOfSeries past the last file."""
    files = list_folder_images(folder)
    if index >= len(files):
        raise EndOfSeries(index, len(files))
    return files[index], len(files)


def _drop_overrun_runs(folder: str, count: int) -> int:
    """
    Remove queued runs of this node that would also start past the end of ``folder``.
    Other queued work is left alone. Returns the number of removed runs.
    """
    try:
        from server import PromptServer
        queue = PromptServer.instance.prompt_queue
    except Exception:
        return 0
    folder_norm = os.path.normcase(os.path.normpath(_clean_folder(folder)))

    def overruns(item) -> bool:
        prompt = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}
        for node in prompt.values():
            if not isinstance(node, dict) or node.get("class_type") != NODE_ID:
                continue
            inputs = node.get("inputs", {})
            if inputs.get("source") != "folder":
                continue
            index, path = inputs.get("index"), inputs.get("folder_path")
            if not isinstance(index, int) or index < count:
                continue
            # a linked folder_path can't be resolved here; assume it is the same series
            if isinstance(path, list) or (
                isinstance(path, str) and os.path.normcase(os.path.normpath(_clean_folder(path))) == folder_norm
            ):
                return True
        return False

    removed = 0
    while queue.delete_queue_item(overruns):
        removed += 1
    return removed


# ----------------------------------------------------------------------
# node
# ----------------------------------------------------------------------

class LoadAndResizeImageWithFilename:
    """
    Loads an image from disk (single file or the next file of a folder series),
    optionally crops it (rectangle, freehand shape or MaskEditor mask), optionally
    resizes it, extracts its mask (alpha channel) and outputs the filename
    (without extension) as a STRING.
    """

    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [
            f for f in os.listdir(input_dir)
            if os.path.isfile(os.path.join(input_dir, f))
        ]
        return {
            "required": {
                "image": (sorted(files), {"image_upload": True}),
                "resize": ("BOOLEAN", {"default": False}),
                "width": (
                    "INT",
                    {
                        "default": 512,
                        "min": 1,
                        "max": 16384,
                        "step": 1,
                        "tooltip": "Target width (only used when resize is enabled)",
                    },
                ),
                "height": (
                    "INT",
                    {
                        "default": 512,
                        "min": 1,
                        "max": 16384,
                        "step": 1,
                        "tooltip": "Target height (only used when resize is enabled)",
                    },
                ),
                "keep_proportion": ("BOOLEAN", {"default": False}),
                "divisible_by": (
                    "INT",
                    {
                        "default": 32,
                        "min": 1,
                        "max": 256,
                        "step": 1,
                        "tooltip": "Round output dimensions to be divisible by this value",
                    },
                ),
                "upscale_method": (
                    [
                        "nearest-exact",
                        "bilinear",
                        "area",
                        "bicubic",
                        "lanczos",
                    ],
                    {"default": "lanczos"},
                ),
                "source": (
                    ["single image", "folder"],
                    {
                        "default": "single image",
                        "tooltip": "single image: the file picked above. folder: the file at 'index' in 'folder_path'",
                    },
                ),
                "folder_path": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Folder with the image series (only used when source = folder)",
                    },
                ),
                "index": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0xFFFFFFFF,
                        "step": 1,
                        "control_after_generate": "increment",
                        "tooltip": "Position in the folder (0 = first file, sorted by name). "
                                   "'increment' loads the next file with every queued run; "
                                   "the series stops after the last file",
                    },
                ),
                "crop_mode": (
                    ["none", "rectangle", "freehand", "mask"],
                    {
                        "default": "none",
                        "tooltip": "rectangle: crop to the rectangle drawn in the preview. "
                                   "freehand: crop to the shape painted in the preview. "
                                   "mask: crop to the mask painted in the MaskEditor (right-click -> Open in MaskEditor). "
                                   "With freehand and mask everything outside the shape is filled with fill_color",
                    },
                ),
                "fill_color": (
                    list(FILL_COLORS.keys()),
                    {
                        "default": "yellow",
                        "tooltip": "Colour for the area outside the freehand shape / mask",
                    },
                ),
                "crop_data": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Written by the crop editor in the node preview",
                    },
                ),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT", "STRING", "INT", "INT")
    RETURN_NAMES = ("image", "mask", "width", "height", "filename", "index", "file_count")
    FUNCTION = "load_image"
    CATEGORY = "KJNodes/image"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pil_to_tensor(pil_img: Image.Image) -> torch.Tensor:
        """Convert a PIL RGB image to a (1, H, W, 3) float32 tensor."""
        arr = np.array(pil_img).astype(np.float32) / 255.0
        return torch.from_numpy(arr).unsqueeze(0)

    @staticmethod
    def _alpha_to_mask(pil_img: Image.Image) -> torch.Tensor:
        """
        Extract the alpha channel as a (1, H, W) float32 mask tensor.
        If no alpha channel exists an all-zero mask is returned.
        """
        if "A" in pil_img.getbands():
            alpha = np.array(pil_img.getchannel("A")).astype(np.float32) / 255.0
            # Invert: in ComfyUI convention mask=1 means "masked / selected"
            mask = 1.0 - alpha
        else:
            w, h = pil_img.size
            mask = np.zeros((h, w), dtype=np.float32)
        return torch.from_numpy(mask).unsqueeze(0)

    @staticmethod
    def _resize(
        tensor: torch.Tensor,
        target_w: int,
        target_h: int,
        keep_proportion: bool,
        divisible_by: int,
        method: str,
    ):
        """
        Resize a (B, H, W, C) image tensor.
        Returns the resized tensor together with the final (width, height).
        """
        _, orig_h, orig_w, _ = tensor.shape

        if keep_proportion:
            ratio = min(target_w / orig_w, target_h / orig_h)
            target_w = int(orig_w * ratio)
            target_h = int(orig_h * ratio)

        if divisible_by > 1:
            target_w = max(1, (target_w // divisible_by) * divisible_by)
            target_h = max(1, (target_h // divisible_by) * divisible_by)

        # common_upscale expects (B, C, H, W)
        t = tensor.movedim(-1, 1)
        t = common_upscale(t, target_w, target_h, method, "disabled")
        t = t.movedim(1, -1)
        return t, target_w, target_h

    # ------------------------------------------------------------------
    # crop helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_crop_data(crop_data: str) -> dict:
        if not crop_data or not crop_data.strip():
            return {}
        try:
            data = json.loads(crop_data)
        except json.JSONDecodeError:
            print(f"[{NODE_ID}] ignoring invalid crop_data: {crop_data[:80]!r}")
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _rect_to_pixels(rect, img_w: int, img_h: int) -> Optional[Tuple[int, int, int, int]]:
        """Relative [x, y, w, h] -> clamped pixel box (x0, y0, x1, y1), or None if unusable."""
        try:
            x, y, w, h = (float(v) for v in rect)
        except (TypeError, ValueError):
            return None
        x0 = int(round(min(max(x, 0.0), 1.0) * img_w))
        y0 = int(round(min(max(y, 0.0), 1.0) * img_h))
        x1 = int(round(min(max(x + w, 0.0), 1.0) * img_w))
        y1 = int(round(min(max(y + h, 0.0), 1.0) * img_h))
        if x1 - x0 < 1 or y1 - y0 < 1:
            return None
        return x0, y0, x1, y1

    @staticmethod
    def _render_shape(strokes, img_w: int, img_h: int) -> np.ndarray:
        """
        Paint the freehand strokes into a (H, W) bool array at full resolution.
        Points are relative (0..1); brush size is relative to the image width.
        """
        canvas = Image.new("L", (img_w, img_h), 0)
        draw = ImageDraw.Draw(canvas)
        for stroke in strokes or []:
            if not isinstance(stroke, dict):
                continue
            pts = [(float(p[0]) * img_w, float(p[1]) * img_h) for p in stroke.get("p", []) if len(p) >= 2]
            if not pts:
                continue
            kind = stroke.get("t", "brush")
            if kind == "lasso":
                if len(pts) >= 3:
                    draw.polygon(pts, fill=255)
                continue
            value = 0 if kind == "erase" else 255
            width = max(1.0, float(stroke.get("s", 0.02)) * img_w)
            r = width / 2.0
            if len(pts) > 1:
                draw.line(pts, fill=value, width=int(round(width)))
            for px, py in pts:
                draw.ellipse((px - r, py - r, px + r, py + r), fill=value)
        return np.array(canvas) > 127

    @staticmethod
    def _editor_mask(image: str, img_w: int, img_h: int) -> np.ndarray:
        """
        The mask painted in the MaskEditor for the file picked in 'image'
        (stored as transparency), scaled to img_w x img_h. True = painted.
        """
        path = folder_paths.get_annotated_filepath(image)
        pil = ImageOps.exif_transpose(Image.open(path))
        if "A" not in pil.getbands():
            return np.zeros((img_h, img_w), dtype=bool)
        alpha = pil.getchannel("A")
        if alpha.size != (img_w, img_h):
            alpha = alpha.resize((img_w, img_h), Image.BILINEAR)
        return np.array(alpha) < 128

    @staticmethod
    def _crop_to_shape(image: torch.Tensor, mask: torch.Tensor, shape: np.ndarray, fill_color: str):
        """Crop to the bounding box of ``shape`` and fill everything outside the shape."""
        ys, xs = np.nonzero(shape)
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        shape_t = torch.from_numpy(shape[y0:y1, x0:x1]).to(image.device)
        out = image[:, y0:y1, x0:x1, :].clone()
        color = torch.tensor(FILL_COLORS.get(fill_color, FILL_COLORS["yellow"]), dtype=out.dtype, device=out.device)
        out[:, ~shape_t] = color
        # mask = the shape (1 = selected), one copy per frame
        out_mask = shape_t.to(mask.dtype).unsqueeze(0).repeat(image.shape[0], 1, 1)
        return out, out_mask

    def _apply_crop(self, image: torch.Tensor, mask: torch.Tensor, crop_mode: str, crop_data: str,
                    fill_color: str, source: str, image_name: str):
        """Crop image (B, H, W, 3) and mask (B, H, W) according to crop_mode."""
        if crop_mode == "none":
            return image, mask
        _, img_h, img_w, _ = image.shape

        if crop_mode == "rectangle":
            box = self._rect_to_pixels(self._parse_crop_data(crop_data).get("rect"), img_w, img_h)
            if box is None:
                print(f"[{NODE_ID}] crop_mode=rectangle but no rectangle drawn, using full image")
                return image, mask
            x0, y0, x1, y1 = box
            return image[:, y0:y1, x0:x1, :], mask[:, y0:y1, x0:x1]

        if crop_mode == "mask":
            if source == "folder":
                shape = self._editor_mask(image_name, img_w, img_h)
            else:
                shape = mask[0].cpu().numpy() > 0.5
            what = "no mask painted in the MaskEditor"
        else:
            shape = self._render_shape(self._parse_crop_data(crop_data).get("strokes"), img_w, img_h)
            what = "nothing painted"

        if not shape.any():
            print(f"[{NODE_ID}] crop_mode={crop_mode} but {what}, using full image")
            return image, mask
        return self._crop_to_shape(image, mask, shape, fill_color)

    # ------------------------------------------------------------------
    # main
    # ------------------------------------------------------------------

    def load_image(
        self,
        image: str,
        resize: bool,
        width: int,
        height: int,
        keep_proportion: bool,
        divisible_by: int,
        upscale_method: str,
        source: str = "single image",
        folder_path: str = "",
        index: int = 0,
        crop_mode: str = "none",
        fill_color: str = "yellow",
        crop_data: str = "",
    ):
        if source == "folder":
            try:
                image_path, file_count = resolve_folder_image(folder_path, index)
            except EndOfSeries as e:
                count = e.args[1]
                removed = _drop_overrun_runs(folder_path, count)
                extra = f" {removed} more queued run(s) of this series were removed." if removed else ""
                raise RuntimeError(
                    f"Series finished: all {count} images of the folder were loaded "
                    f"(index {index} is past the last file).{extra} Set index to 0 to start again."
                ) from None
            index_out = index
        else:
            image_path = folder_paths.get_annotated_filepath(image)
            index_out, file_count = 0, 1

        # ---- derive filename (stem only, no extension) ----------------
        filename_stem = os.path.splitext(os.path.basename(image_path))[0]

        # ---- load all frames (GIF / APNG support) ---------------------
        img_pil = Image.open(image_path)

        output_images = []
        output_masks = []

        for frame in ImageSequence.Iterator(img_pil):
            frame = ImageOps.exif_transpose(frame)
            output_images.append(self._pil_to_tensor(frame.convert("RGB")))
            output_masks.append(self._alpha_to_mask(frame))

        out_image = torch.cat(output_images, dim=0)
        out_mask = torch.cat(output_masks, dim=0)

        # ---- optional crop (before resize) -----------------------------
        out_image, out_mask = self._apply_crop(out_image, out_mask, crop_mode, crop_data, fill_color, source, image)

        # ---- optional resize ------------------------------------------
        if resize:
            out_image, final_w, final_h = self._resize(
                out_image, width, height, keep_proportion, divisible_by, upscale_method
            )
            mask_4d = out_mask.unsqueeze(-1)  # (N, H, W, 1)
            mask_4d, final_w, final_h = self._resize(
                mask_4d, width, height, keep_proportion, divisible_by, upscale_method
            )
            out_mask = mask_4d.squeeze(-1)
        else:
            _, final_h, final_w, _ = out_image.shape

        return out_image, out_mask, final_w, final_h, filename_stem, index_out, file_count

    # ------------------------------------------------------------------
    # ComfyUI cache / IS_CHANGED support
    # ------------------------------------------------------------------

    @staticmethod
    def _file_hash(path: str) -> str:
        m = hashlib.sha256()
        with open(path, "rb") as f:
            m.update(f.read())
        return m.hexdigest()

    @classmethod
    def IS_CHANGED(cls, image, source="single image", folder_path="", index=0, crop_mode="none", **kwargs):
        try:
            if source != "folder":
                return cls._file_hash(folder_paths.get_annotated_filepath(image))
            image_path, count = resolve_folder_image(folder_path, index)
            stat = os.stat(image_path)
            key = f"{image_path}|{count}|{stat.st_mtime_ns}|{stat.st_size}"
            if crop_mode == "mask":
                key += "|" + cls._file_hash(folder_paths.get_annotated_filepath(image))
            return key
        except Exception:
            # let load_image report the actual error
            return float("nan")

    @classmethod
    def VALIDATE_INPUTS(cls, image, source="single image", **kwargs):
        # folder mode is checked when the node runs (folder_path may come from a link)
        if source != "folder" and not folder_paths.exists_annotated_filepath(image):
            return f"Invalid image path: {image}"
        return True
