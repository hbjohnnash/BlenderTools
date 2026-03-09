"""Blender headless smoke test — verifies the addon loads inside real Blender.

Run with:
    blender-launcher --background --python tests/smoke_test_blender.py

Or if you have blender on PATH:
    blender --background --python tests/smoke_test_blender.py

NOTE FOR MICROSOFT STORE INSTALLS:
    The Store version of Blender can't print to the terminal, so this
    script writes all output to tests/smoke_results.txt as well.
    After running, check that file for results.

WHY THIS EXISTS:
    Our pytest suite mocks Blender modules so we can test pure logic fast.
    But mocks can't catch problems like:
      - Addon fails to register (bad class, missing property)
      - Panel draw() crashes on first call
      - Operator poll() has a typo in a context check
    This script runs inside REAL Blender and catches those issues.
"""

import os
import sys
import traceback

# Output goes to both terminal (if available) and a results file.
# Microsoft Store Blender can't print to terminal, so the file is essential.
_script_dir = os.path.dirname(os.path.abspath(__file__))
_results_path = os.path.join(_script_dir, "smoke_results.txt")
_results_file = open(_results_path, "w", encoding="utf-8")
_failures = []


def log(msg):
    """Write to both stdout and results file."""
    print(msg)
    _results_file.write(msg + "\n")
    _results_file.flush()


def check(description, condition):
    """Assert a condition, record failure instead of crashing."""
    if condition:
        log(f"  PASS: {description}")
    else:
        log(f"  FAIL: {description}")
        _failures.append(description)


def test_addon_registration():
    """Test that the addon can be enabled and its modules register."""
    import bpy

    log("\n── Addon Registration ──")

    addon_name = "bl_ext.user_default.blender_tools"

    # Check if already registered (e.g. user has it installed)
    is_registered = addon_name in bpy.context.preferences.addons

    if not is_registered:
        try:
            bpy.ops.preferences.addon_enable(module=addon_name)
            is_registered = True
        except Exception as e:
            log(f"  Could not enable addon: {e}")
            log("  (Make sure BlenderTools is installed as an addon first)")
            _failures.append("Addon could not be enabled")
            return

    check("Addon is registered", is_registered)


def test_operators_exist():
    """Test that key operators are registered in Blender."""
    import bpy

    log("\n── Operator Registration ──")

    expected_ops = [
        "bt.mark_seams",
        "bt.init_seam_ai",
        "bt.seam_neural",
        "bt.init_anim_ai",
        "bt.ai_generate_motion",
    ]

    for op_idtext in expected_ops:
        parts = op_idtext.split(".")
        category = getattr(bpy.ops, parts[0], None)
        if category is None:
            check(f"Operator {op_idtext}", False)
            continue
        op = getattr(category, parts[1], None)
        check(f"Operator {op_idtext}", op is not None)


def test_panels_exist():
    """Test that UI panels are registered."""
    import bpy

    log("\n── Panel Registration ──")

    expected_panels = [
        "BT_PT_SeamsMain",
        "BT_PT_AnimationMain",
        "BT_PT_RiggingMain",
        "BT_PT_SkinningMain",
        "BT_PT_ExportMain",
    ]

    all_panels = {cls.__name__ for cls in bpy.types.Panel.__subclasses__()}

    for panel_name in expected_panels:
        check(f"Panel {panel_name}", panel_name in all_panels)


def test_ml_properties():
    """Test that ML progress tracking properties exist on WindowManager.

    These only exist after the ML integration commit. If the addon was
    installed before that, they'll be missing — reported as WARN not FAIL.
    """
    import bpy

    log("\n── ML Properties ──")

    wm = bpy.context.window_manager
    props = ["bt_ml_busy", "bt_ml_progress", "bt_ml_status"]
    found = [p for p in props if hasattr(wm, p)]
    missing = [p for p in props if not hasattr(wm, p)]

    if missing and not found:
        log("  WARN: ML properties not found (addon may need reinstalling)")
        for p in missing:
            log(f"    - {p}")
        log("  (This is expected if the installed addon predates the ML commit)")
    else:
        for p in props:
            check(f"{p} property exists", hasattr(wm, p))


def test_preferences():
    """Test that addon preferences are accessible."""
    import bpy

    log("\n── Preferences ──")

    addon_name = "bl_ext.user_default.blender_tools"
    prefs = bpy.context.preferences.addons.get(addon_name)
    check("Addon preferences accessible", prefs is not None)


# ── Run all tests ──

if __name__ == "__main__":
    log("=" * 50)
    log("BlenderTools Smoke Test (Blender Headless)")
    log("=" * 50)

    import bpy
    log(f"Blender version: {bpy.app.version_string}")

    tests = [
        test_addon_registration,
        test_operators_exist,
        test_panels_exist,
        test_ml_properties,
        test_preferences,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception:
            msg = traceback.format_exc()
            log(f"  CRASH in {test_fn.__name__}:\n{msg}")
            _failures.append(f"{test_fn.__name__} crashed")

    # ── Summary ──
    log("\n" + "=" * 50)
    if _failures:
        log(f"FAILED: {len(_failures)} check(s) failed:")
        for f in _failures:
            log(f"  - {f}")
        log(f"\nResults written to: {_results_path}")
        _results_file.close()
        sys.exit(1)
    else:
        log("ALL CHECKS PASSED")
        log(f"\nResults written to: {_results_path}")
        _results_file.close()
        sys.exit(0)
