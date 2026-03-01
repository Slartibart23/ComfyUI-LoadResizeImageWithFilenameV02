"""
ComfyUI-LoadResizeImageWithFilename
====================================
A single-node extension for ComfyUI that combines:
  • Image loading with mask (alpha) extraction
  • Optional resize with proportion-keeping
  • STRING output for the loaded file's name (stem without extension)

Based on KJNodes LoadAndResizeImage by kijai
  https://github.com/kijai/ComfyUI-KJNodes
Extended by Slartibart23
"""

from .nodes.load_resize_image_node import LoadAndResizeImageWithFilename

NODE_CLASS_MAPPINGS = {
    "LoadAndResizeImageWithFilename": LoadAndResizeImageWithFilename,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadAndResizeImageWithFilename": "Load & Resize Image + Filename",
}

WEB_DIRECTORY = "./web/js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
