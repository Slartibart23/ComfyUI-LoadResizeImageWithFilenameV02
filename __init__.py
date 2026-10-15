"""
ComfyUI-LoadResizeImageWithFilename
====================================
A single-node extension for ComfyUI that combines:
  • Image loading with mask (alpha) extraction
  • Optional resize with proportion-keeping
  • STRING output for the loaded file's name (stem without extension)
  • Folder series: one file per queued run
  • Crop editor in the node: rectangle or freehand shape

Based on KJNodes LoadAndResizeImage by kijai
  https://github.com/kijai/ComfyUI-KJNodes
Extended by Slartibart23
"""

import os
from urllib.parse import quote

from aiohttp import web
from server import PromptServer

from .nodes.load_resize_image_node import LoadAndResizeImageWithFilename, resolve_folder_image


@PromptServer.instance.routes.get("/lrif/folder_image")
async def lrif_folder_image(request):
    """Serve the image at ?index= of ?folder= so the crop editor can preview folder series."""
    folder = request.query.get("folder", "")
    end_of_folder = request.query.get("end", "wrap")
    try:
        index = int(request.query.get("index", "0"))
        path, effective, count = resolve_folder_image(folder, index, end_of_folder)
    except (ValueError, FileNotFoundError, IndexError) as e:
        return web.json_response({"error": str(e)}, status=404)
    return web.FileResponse(path, headers={
        "Cache-Control": "no-store",
        "X-LRIF-Filename": quote(os.path.basename(path)),
        "X-LRIF-Index": str(effective),
        "X-LRIF-Count": str(count),
    })


NODE_CLASS_MAPPINGS = {
    "LoadAndResizeImageWithFilename": LoadAndResizeImageWithFilename,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadAndResizeImageWithFilename": "Load & Resize Image + Filename",
}

WEB_DIRECTORY = "./web/js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
