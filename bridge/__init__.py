"""LLM Bridge subsystem — HTTP server for Claude Code integration."""

from . import panels

_server_instance = None


def register():
    panels.register()


def unregister():
    # Stop server if running
    from .server import stop_server
    stop_server()
    panels.unregister()
