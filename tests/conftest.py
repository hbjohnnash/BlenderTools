"""Shared test fixtures and Blender module mocks.

This file runs before any test. It injects fake 'bpy', 'bmesh',
'mathutils', etc. into sys.modules so that our addon code can be
imported and tested outside of Blender.

HOW IT WORKS:
    When Python sees 'import bpy', it checks sys.modules first.
    If we put a Mock object there, Python uses that instead of
    searching for the real module (which doesn't exist outside Blender).

    Blender addon modules use deep relative imports like
    ``from ...core.ml.base_adapter import BaseModelAdapter``.
    Outside Blender these go beyond the top-level package, so we
    patch ``builtins.__import__`` to fall back to absolute imports
    and stub package __init__ files to prevent heavy import chains.
"""

import builtins
import math
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Inject fake Blender modules ──
# These must be set up BEFORE any addon code is imported.

_BLENDER_MODULES = [
    "bpy",
    "bpy.types",
    "bpy.props",
    "bpy.utils",
    "bpy.ops",
    "bpy.ops.object",
    "bpy.ops.wm",
    "bpy.data",
    "bpy_extras",
    "bpy_extras.anim_utils",
    "bmesh",
    "mathutils",
    "gpu",
    "gpu_extras",
    "gpu_extras.batch",
    "blf",
]

for mod_name in _BLENDER_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()


# ── Minimal Vector mock ──
# The real mathutils.Vector supports arithmetic, cross products, etc.
# We implement just enough for geometry tests to work.

class _MockVector:
    """Lightweight stand-in for mathutils.Vector."""

    __slots__ = ("x", "y", "z")

    def __init__(self, data):
        self.x, self.y, self.z = float(data[0]), float(data[1]), float(data[2])

    def __repr__(self):
        return f"Vector(({self.x}, {self.y}, {self.z}))"

    def __getitem__(self, i):
        return (self.x, self.y, self.z)[i]

    def __sub__(self, other):
        return _MockVector((self.x - other.x, self.y - other.y, self.z - other.z))

    def __add__(self, other):
        return _MockVector((self.x + other.x, self.y + other.y, self.z + other.z))

    def __mul__(self, scalar):
        return _MockVector((self.x * scalar, self.y * scalar, self.z * scalar))

    __rmul__ = __mul__

    def cross(self, other):
        return _MockVector((
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        ))

    @property
    def length(self):
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    def normalize(self):
        mag = self.length
        if mag > 1e-8:
            self.x /= mag
            self.y /= mag
            self.z /= mag
        return self

    def normalized(self):
        return self.copy().normalize()

    def dot(self, other):
        return self.x * other.x + self.y * other.y + self.z * other.z

    def angle(self, other, fallback=0.0):
        dot = self.x * other.x + self.y * other.y + self.z * other.z
        dot = max(-1.0, min(1.0, dot))
        return math.acos(dot)

    def copy(self):
        return _MockVector((self.x, self.y, self.z))


_mock_mathutils = sys.modules["mathutils"]
_mock_mathutils.Vector = _MockVector

# Make bpy.props return plain values so class attributes resolve
_mock_props = sys.modules["bpy.props"]
_mock_props.BoolProperty = lambda **kw: kw.get("default", False)
_mock_props.IntProperty = lambda **kw: kw.get("default", 0)
_mock_props.FloatProperty = lambda **kw: kw.get("default", 0.0)
_mock_props.StringProperty = lambda **kw: kw.get("default", "")
_mock_props.EnumProperty = lambda **kw: kw.get("default", "")

# Add the project root to sys.path so we can import addon modules
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ── Stub addon subpackages ──
# Blender addon packages use deep relative imports (e.g. from ...core.ml)
# that don't resolve outside Blender's module hierarchy. We:
# 1. Stub package __init__ modules so their heavy import chains don't run
# 2. Patch builtins.__import__ to redirect relative imports that exceed
#    the top-level package depth to absolute imports instead.

for _pkg_name in ["seams", "seams.ml", "animation", "animation.ml"]:
    if _pkg_name not in sys.modules:
        _mod = types.ModuleType(_pkg_name)
        _mod.__path__ = [str(_project_root / _pkg_name.replace(".", "/"))]
        _mod.__package__ = _pkg_name
        sys.modules[_pkg_name] = _mod

_original_import = builtins.__import__


def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Redirect relative imports that exceed package depth to absolute.

    Inside Blender, ``from ...core.ml.base_adapter import X`` works because
    the addon sits three levels deep.  Outside Blender the packages are
    top-level, so we catch the overshoot and retry as an absolute import.
    """
    if level > 0 and globals:
        package = globals.get("__package__") or ""
        if package:
            parts = package.split(".")
            if parts[0] and level > len(parts):
                try:
                    return _original_import(name, globals, locals, fromlist, 0)
                except ImportError:
                    pass
    return _original_import(name, globals, locals, fromlist, level)


builtins.__import__ = _patched_import


# ── Fixtures ──
# Fixtures are reusable setup/teardown helpers that tests can request
# by name in their function arguments.

@pytest.fixture
def tmp_model_dir(tmp_path):
    """Provide a temporary directory for model cache tests.

    tmp_path is a built-in pytest fixture that gives a unique
    temporary directory for each test, automatically cleaned up.
    """
    return tmp_path / "models"


@pytest.fixture
def sample_bvh_file(tmp_path):
    """Create a minimal BVH file for parsing tests."""
    bvh_content = """\
HIERARCHY
ROOT Hips
{
  OFFSET 0.000000 0.000000 0.000000
  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
  JOINT Spine
  {
    OFFSET 0.000000 5.000000 0.000000
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT Head
    {
      OFFSET 0.000000 5.000000 0.000000
      CHANNELS 3 Zrotation Xrotation Yrotation
      End Site
      {
        OFFSET 0.000000 2.000000 0.000000
      }
    }
  }
}
MOTION
Frames: 3
Frame Time: 0.033333
0.0 1.0 0.0 0.0 0.0 0.0 0.0 10.0 0.0 0.0 0.0 0.0
0.5 1.0 0.0 5.0 0.0 0.0 0.0 15.0 0.0 0.0 5.0 0.0
1.0 1.0 0.0 10.0 0.0 0.0 0.0 20.0 0.0 0.0 10.0 0.0
"""
    bvh_path = tmp_path / "test_motion.bvh"
    bvh_path.write_text(bvh_content, encoding="utf-8")
    return bvh_path
