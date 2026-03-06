"""PropertyGroups for skeleton scanner UI state."""

import math

import bpy
from bpy.props import (
    StringProperty, EnumProperty, BoolProperty, FloatProperty,
    IntProperty, CollectionProperty, PointerProperty,
)

BONE_MODULE_TYPE_ITEMS = [
    ('root', "Root", "Root/reference bone"),
    ('spine', "Spine", "Spine chain"),
    ('arm', "Arm", "Arm chain (FK+IK)"),
    ('leg', "Leg", "Leg chain (FK+IK)"),
    ('neck_head', "Neck/Head", "Neck and head"),
    ('tail', "Tail", "Tail chain"),
    ('jaw', "Jaw", "Jaw bone(s)"),
    ('eye', "Eye", "Eye bone"),
    ('wing', "Wing", "Wing chain (FK+IK)"),
    ('tentacle', "Tentacle", "Tentacle chain"),
    ('finger', "Finger", "Finger chain"),
    ('generic', "Generic", "Generic FK chain"),
]

CHAIN_MODULE_TYPE_ITEMS = BONE_MODULE_TYPE_ITEMS + [
    ('skip', "Skip", "Skip this entire chain"),
]

SIDE_ITEMS = [
    ('C', "Center", ""),
    ('L', "Left", ""),
    ('R', "Right", ""),
]


class BT_ScanBoneItem(bpy.types.PropertyGroup):
    bone_name: StringProperty(name="Bone")
    role: StringProperty(name="Role")
    side: EnumProperty(name="Side", items=SIDE_ITEMS, default='C')
    module_type: EnumProperty(name="Type", items=BONE_MODULE_TYPE_ITEMS, default='generic')
    chain_id: StringProperty(name="Chain ID")
    skip: BoolProperty(name="Skip", default=False)
    confidence: FloatProperty(name="Confidence", min=0.0, max=1.0)


class BT_ScanChainItem(bpy.types.PropertyGroup):
    chain_id: StringProperty(name="Chain ID")
    module_type: EnumProperty(name="Type", items=CHAIN_MODULE_TYPE_ITEMS, default='generic')
    side: EnumProperty(name="Side", items=SIDE_ITEMS, default='C')
    # Build config — whether to generate FK/IK controls
    ik_enabled: BoolProperty(name="IK", default=True)
    fk_enabled: BoolProperty(name="FK", default=True)
    ik_snap: BoolProperty(
        name="Snap",
        description="Enable FK/IK snapping (limits IK to 2 bones for stable switching)",
        default=False,
    )
    # Runtime state — which mode is currently active (only used when wrap rig exists)
    ik_active: BoolProperty(name="IK Active", default=False)
    bone_count: IntProperty(name="Bones", default=0)


class BT_ScanData(bpy.types.PropertyGroup):
    skeleton_type: StringProperty(name="Skeleton Type", default="")
    confidence: FloatProperty(name="Confidence", min=0.0, max=1.0)
    is_scanned: BoolProperty(name="Scanned", default=False)
    has_wrap_rig: BoolProperty(name="Has Wrap Rig", default=False)

    bones: CollectionProperty(type=BT_ScanBoneItem)
    chains: CollectionProperty(type=BT_ScanChainItem)
    unmapped_bones: StringProperty(
        name="Unmapped Bones",
        description="Comma-separated list of unmapped bone names",
        default="",
    )

    active_chain_index: IntProperty(name="Active Chain", default=0)
    active_bone_index: IntProperty(name="Active Bone", default=0)

    skip_pattern: StringProperty(
        name="Pattern",
        description="Glob pattern for batch skip (e.g. Automatic*, *Piston*, *Spring*)",
        default="",
    )

    hidden_collections: StringProperty(
        name="Hidden Collections",
        description="Comma-separated names of collections hidden during rig creation",
        default="",
    )

    # Floor contact settings
    floor_enabled: BoolProperty(name="Floor Contact", default=False)
    floor_level: FloatProperty(
        name="Floor Level",
        description="World-space Z value for the floor plane",
        default=0.0,
        unit='LENGTH',
    )
    floor_toe_bend: BoolProperty(
        name="Toe Auto-Bend",
        description="Automatically bend toes upward when foot contacts floor",
        default=True,
    )
    floor_toe_angle: FloatProperty(
        name="Max Toe Angle",
        description="Maximum toe bend angle when foot is at floor level",
        default=math.radians(45.0),
        min=0.0,
        max=math.radians(90.0),
        subtype='ANGLE',
    )


classes = (
    BT_ScanBoneItem,
    BT_ScanChainItem,
    BT_ScanData,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.bt_scan = PointerProperty(type=BT_ScanData)


def unregister():
    del bpy.types.Object.bt_scan
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
