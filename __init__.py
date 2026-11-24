"""ComfyUI-H3MD-Expression - expression studio for H3MD / MiniMax H3 (and plain pictures).
A companion to ComfyUI-H3MD-Director; independent of it.
Face engine built in (face_engine/: LivePortrait networks from Kuaishou's MIT code + OpenCV YuNet), no other plugin needed."""
from .h3md_expression_nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from . import h3md_expression_studio as _studio

_studio.register_routes()
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
