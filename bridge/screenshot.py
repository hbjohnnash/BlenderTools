"""Viewport capture via gpu module (Blender 5.0 — no legacy BGL)."""

import base64
import os
import tempfile

import bpy


def capture_viewport(width=960, height=540):
    """Capture the current viewport as a base64-encoded PNG.

    Uses gpu module for Blender 5.0 compatibility.

    Args:
        width: Image width.
        height: Image height.

    Returns:
        Dict with success status and base64 image data.
    """
    try:

        # Use Blender's built-in opengl render
        # Save to temp file, read back as base64
        tmp_path = os.path.join(tempfile.gettempdir(), "bt_screenshot.png")

        # Use the viewport render method
        scene = bpy.context.scene
        old_filepath = scene.render.filepath
        old_format = scene.render.image_settings.file_format
        old_res_x = scene.render.resolution_x
        old_res_y = scene.render.resolution_y

        scene.render.filepath = tmp_path
        scene.render.image_settings.file_format = 'PNG'
        scene.render.resolution_x = width
        scene.render.resolution_y = height

        # Render viewport
        bpy.ops.render.opengl(write_still=True)

        # Restore
        scene.render.filepath = old_filepath
        scene.render.image_settings.file_format = old_format
        scene.render.resolution_x = old_res_x
        scene.render.resolution_y = old_res_y

        # Read and encode
        if os.path.exists(tmp_path):
            with open(tmp_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("ascii")
            os.remove(tmp_path)
            return {
                "success": True,
                "format": "png",
                "width": width,
                "height": height,
                "data": img_data,
            }
        else:
            return {"success": False, "error": "Screenshot file not created"}

    except Exception as e:
        return {"success": False, "error": str(e)}
