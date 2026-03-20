"""LLM Bridge area content builder."""

from .. import theme as T
from ..widget_base import HStack, VStack
from ..widgets import Button, Label


def build_bridge(context):
    """Build the bridge widget tree."""
    try:
        from ...bridge.server import is_running
        running = is_running()
    except Exception:
        running = False

    children = []

    if running:
        try:
            prefs = context.preferences.addons["BlenderTools"].preferences
            port = prefs.bridge_port
        except (KeyError, AttributeError):
            from ...core.constants import BRIDGE_PORT
            port = BRIDGE_PORT
        children.append(HStack([
            Label("Running", size=T.FONT_SIZE_SMALL, color=T.TEXT_PRIMARY),
            Label(f":{port}", size=T.FONT_SIZE_SMALL, color=T.TEXT_SECONDARY),
        ], gap=8, padding=(0, 0, 0, 0)))
        children.append(Button("Stop Bridge", action_id="stop_bridge",
                               style=Button.STYLE_DANGER))
    else:
        children.append(Label("Stopped", size=T.FONT_SIZE_SMALL,
                              color=T.TEXT_SECONDARY))
        children.append(Button("Start Bridge", action_id="start_bridge",
                               style=Button.STYLE_PRIMARY))

    return VStack(children, gap=T.ITEM_GAP, padding=(0, 0, 0, 0))
