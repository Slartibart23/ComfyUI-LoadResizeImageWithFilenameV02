"""
LoadAndResizeImageWithFilename Node
Based on KJNodes LoadAndResizeImage by kijai (https://github.com/kijai/ComfyUI-KJNodes)
Extended with filename output by Slartibart23

Compatible with Python 3.13+
"""

import os
import hashlib
import torch
import numpy as np
from PIL import Image, ImageOps, ImageSequence

import folder_paths
from comfy.utils import common_upscale


class LoadAndResizeImageWithFilename:
    """
    Loads an image from disk, optionally resizes it, extracts its mask (alpha channel),
    and outputs the filename (without extension) as a STRING for use in downstream nodes.
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
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT", "STRING")
    RETURN_NAMES = ("image", "mask", "width", "height", "filename")
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
    ):
        image_path = folder_paths.get_annotated_filepath(image)

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

        return out_image, out_mask, final_w, final_h, filename_stem

    # ------------------------------------------------------------------
    # ComfyUI cache / IS_CHANGED support
    # ------------------------------------------------------------------

    @classmethod
    def IS_CHANGED(cls, image, **kwargs):
        image_path = folder_paths.get_annotated_filepath(image)
        m = hashlib.sha256()
        with open(image_path, "rb") as f:
            m.update(f.read())
        return m.hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, image, **kwargs):
        if not folder_paths.exists_annotated_filepath(image):
            return f"Invalid image path: {image}"
        return True
