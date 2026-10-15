"""
ComfyUI-LoadResizeImageWithFilename
====================================
A single-node extension for ComfyUI that combines:
  • Image loading with mask (alpha) extraction
  • Optional resize with proportion-keeping
  • STRING output for the loaded file's name (stem without extension)
  • Folder series: one file per queued run, stops after the last file
  • Crop: rectangle / freehand shape drawn in the node, or the MaskEditor mask

Based on KJNodes LoadAndResizeImage by kijai
  https://github.com/kijai/ComfyUI-KJNodes
Extended by Slartibart23
"""

import os
from urllib.parse import quote

from aiohttp import web
from server import PromptServer

from .nodes.load_resize_image_node import LoadAndResizeImageWithFilename, EndOfSeries, resolve_folder_image


@PromptServer.instance.routes.get("/lrif/folder_image")
async def lrif_folder_image(request):
    """Serve the image at ?index= of ?folder= so the crop editor can preview folder series."""
    folder = request.query.get("folder", "")
    try:
        index = int(request.query.get("index", "0"))
        path, count = resolve_folder_image(folder, index)
    except EndOfSeries as e:
        return web.json_response(
            {"error": f"Series finished: all {e.args[1]} images loaded. Set index to 0 to start again"},
            status=404,
        )
    except (ValueError, FileNotFoundError) as e:
        return web.json_response({"error": str(e)}, status=404)
    return web.FileResponse(path, headers={
        "Cache-Control": "no-store",
        "X-LRIF-Filename": quote(os.path.basename(path)),
        "X-LRIF-Index": str(index),
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
