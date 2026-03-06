"""Seam preset discovery and listing."""

from ..core.utils import get_presets_directory
from ..core.constants import SEAM_PRESET_DIR


def list_seam_presets():
    """Return a list of available seam preset names."""
    preset_dir = get_presets_directory() / SEAM_PRESET_DIR
    if not preset_dir.exists():
        return []
    return [p.stem for p in preset_dir.glob("*.json")]


def get_preset_items(self, context):
    """EnumProperty callback for seam presets."""
    presets = list_seam_presets()
    if not presets:
        return [('NONE', "No Presets", "No seam presets found")]
    return [(p, p.replace("_", " ").title(), f"Apply {p} preset") for p in presets]
