"""
LoadAndResizeImageWithFilename Node
Based on KJNodes LoadAndResizeImage by kijai (https://github.com/kijai/ComfyUI-KJNodes)
Extended with filename output, folder series and crop editor by Slartibart23

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


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif")

FILL_COLORS = {
    "red": (1.0, 0.0, 0.0),
    "green": (0.0, 1.0, 0.0),
    "yellow": (1.0, 1.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
    "white": (1.0, 1.0, 1.0),
    "black": (0.0, 0.0, 0.0),
}


# ----------------------------------------------------------------------
# folder series helpers (also used by the web route in __init__.py)
# ----------------------------------------------------------------------

def _natural_key(name: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


def list_folder_images(folder: str) -> List[str]:
    """Return the image files in ``folder`` (not recursive), naturally sorted."""
    folder = folder.strip().strip('"')
    if not folder or not os.path.isdir(folder):
        raise FileNotFoundError(f"Folder not found: {folder!r}")
    files = [
        f for f in os.listdir(folder)
        if f.lower().endswith(IMAGE_EXTENSIONS) and os.path.isfile(os.path.join(folder, f))
    ]
    if not files:
        raise FileNotFoundError(f"No images ({', '.join(IMAGE_EXTENSIONS)}) in folder: {folder!r}")
    return [os.path.join(folder, f) for f in sorted(files, key=_natural_key)]


def resolve_folder_image(folder: str, index: int, end_of_folder: str) -> Tuple[str, int, int]:
    """
    Pick the file for ``index``. Returns (path, effective_index, file_count).
    ``wrap`` starts over at the first file, ``stop`` raises once the series is done.
    """
    files = list_folder_images(folder)
    count = len(files)
    if end_of_folder == "stop" and index >= count:
        raise IndexError(
            f"End of series reached: index {index}, but the folder only has {count} images "
            f"(0 to {count - 1}). Reset the index to start again."
        )
    effective = index % count
    return files[effective], effective, count


# ----------------------------------------------------------------------
# node
# ----------------------------------------------------------------------

class LoadAndResizeImageWithFilename:
    """
    Loads an image from disk (single file or the next file of a folder series),
    optionally crops it (rectangle or freehand shape), optionally resizes it,
    extracts its mask and outputs the filename (without extension) as a STRING.
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
                        "default": 2,
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
                                   "'increment' loads the next file with every queued run",
                    },
                ),
                "end_of_folder": (
                    ["wrap", "stop"],
                    {
                        "default": "wrap",
                        "tooltip": "wrap: start over at the first file. stop: fail once all files were loaded",
                    },
                ),
                "crop_mode": (
                    ["none", "rectangle", "freehand"],
                    {
                        "default": "none",
                        "tooltip": "rectangle: crop to the rectangle drawn in the preview. "
                                   "freehand: crop to the painted shape, everything outside it is filled with fill_color",
                    },
                ),
                "fill_color": (
                    list(FILL_COLORS.keys()),
                    {
                        "default": "red",
                        "tooltip": "Colour for the area outside the freehand shape",
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

    @staticmethod
    def _parse_crop_data(crop_data: str) -> dict:
        if not crop_data or not crop_data.strip():
            return {}
        try:
            data = json.loads(crop_data)
        except json.JSONDecodeError:
            print(f"[LoadAndResizeImageWithFilename] ignoring invalid crop_data: {crop_data[:80]!r}")
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

    def _apply_crop(self, image: torch.Tensor, mask: torch.Tensor, crop_mode: str, crop_data: str, fill_color: str):
        """Crop image (B, H, W, 3) and mask (B, H, W) according to the crop editor data."""
        if crop_mode == "none":
            return image, mask

        data = self._parse_crop_data(crop_data)
        _, img_h, img_w, _ = image.shape

        if crop_mode == "rectangle":
            box = self._rect_to_pixels(data.get("rect"), img_w, img_h)
            if box is None:
                print("[LoadAndResizeImageWithFilename] crop_mode=rectangle but no rectangle drawn, using full image")
                return image, mask
            x0, y0, x1, y1 = box
            return image[:, y0:y1, x0:x1, :], mask[:, y0:y1, x0:x1]

        # freehand
        shape = self._render_shape(data.get("strokes"), img_w, img_h)
        ys, xs = np.nonzero(shape)
        if len(xs) == 0:
            print("[LoadAndResizeImageWithFilename] crop_mode=freehand but nothing painted, using full image")
            return image, mask
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1

        shape_t = torch.from_numpy(shape[y0:y1, x0:x1]).to(image.device)
        out = image[:, y0:y1, x0:x1, :].clone()
        color = torch.tensor(FILL_COLORS.get(fill_color, FILL_COLORS["red"]), dtype=out.dtype, device=out.device)
        out[:, ~shape_t] = color
        # mask = the painted shape (1 = selected), one copy per frame
        out_mask = shape_t.to(mask.dtype).unsqueeze(0).repeat(image.shape[0], 1, 1)
        return out, out_mask

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
        end_of_folder: str = "wrap",
        crop_mode: str = "none",
        fill_color: str = "red",
        crop_data: str = "",
    ):
        if source == "folder":
            image_path, index_out, file_count = resolve_folder_image(folder_path, index, end_of_folder)
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
            frame_rgb = frame.convert("RGB")

            img_tensor = self._pil_to_tensor(frame_rgb)
            mask_tensor = self._alpha_to_mask(frame)

            output_images.append(img_tensor)
            output_masks.append(mask_tensor)

        if len(output_images) == 1:
            out_image = output_images[0]
            out_mask = output_masks[0]
        else:
            out_image = torch.cat(output_images, dim=0)
            # Stack masks: (N, H, W)
            out_mask = torch.cat(output_masks, dim=0)

        # ---- optional crop (before resize) -----------------------------
        out_image, out_mask = self._apply_crop(out_image, out_mask, crop_mode, crop_data, fill_color)

        # ---- optional resize ------------------------------------------
        if resize:
            out_image, final_w, final_h = self._resize(
                out_image, width, height, keep_proportion, divisible_by, upscale_method
            )
            # Resize mask too (add channel dim for common_upscale)
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

    @classmethod
    def IS_CHANGED(cls, image, source="single image", folder_path="", index=0, end_of_folder="wrap", **kwargs):
        try:
            if source == "folder":
                image_path, _, count = resolve_folder_image(folder_path, index, end_of_folder)
                stat = os.stat(image_path)
                return f"{image_path}|{count}|{stat.st_mtime_ns}|{stat.st_size}"
            image_path = folder_paths.get_annotated_filepath(image)
        except Exception:
            # let load_image report the actual error
            return float("nan")
        m = hashlib.sha256()
        with open(image_path, "rb") as f:
            m.update(f.read())
        return m.hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, image, source="single image", **kwargs):
        # folder mode is checked when the node runs (folder_path may come from a link)
        if source != "folder" and not folder_paths.exists_annotated_filepath(image):
            return f"Invalid image path: {image}"
        return True
