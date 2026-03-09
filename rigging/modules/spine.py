"""Spine rig module — three-tier (CTRL → MCH → DEF) FK chain with optional IK spline."""

from mathutils import Vector

from ..module_base import RigModule
from . import register_module

_CON_PREFIX = "BT_Spine_"


@register_module
class SpineModule(RigModule):
    module_type = "spine"
    display_name = "Spine"
    category = "organic"

    def __init__(self, config):
        super().__init__(config)
        self.bone_count = self.options.get("bone_count", 4)
        self.ik_spline = self.options.get("ik_spline", False)

    def create_bones(self, armature, edit_bones):
        names = []
        pos = Vector(self.position)
        spacing = 0.15

        # --- DEF layer ---
        for i in range(self.bone_count):
            bn = self.def_name(f"{i+1:03d}")
            eb = edit_bones.new(bn)
            eb.head = pos + Vector((0, 0, spacing * i))
            eb.tail = pos + Vector((0, 0, spacing * (i + 1)))
            eb.use_deform = True
            if i > 0:
                prev = self.def_name(f"{i:03d}")
                eb.parent = edit_bones[prev]
                eb.use_connect = True
            names.append(bn)

        # --- MCH layer ---
        for i in range(self.bone_count):
            mn = self.mch_name(f"{i+1:03d}")
            eb = edit_bones.new(mn)
            src = edit_bones[self.def_name(f"{i+1:03d}")]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            if i > 0:
                prev = self.mch_name(f"{i:03d}")
                eb.parent = edit_bones[prev]
                eb.use_connect = True
            names.append(mn)

        # --- CTRL layer ---
        for i in range(self.bone_count):
            cn = self.ctrl_name(f"FK_{i+1:03d}")
            eb = edit_bones.new(cn)
            src = edit_bones[self.def_name(f"{i+1:03d}")]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            if i > 0:
                prev = self.ctrl_name(f"FK_{i:03d}")
                eb.parent = edit_bones[prev]
            names.append(cn)

        # IK spline control bones (top and bottom handles)
        if self.ik_spline:
            for label, idx in [("IK_Bottom", 0), ("IK_Top", self.bone_count - 1)]:
                cn = self.ctrl_name(label)
                eb = edit_bones.new(cn)
                src = edit_bones[self.def_name(f"{idx+1:03d}")]
                eb.head = src.head.copy()
                eb.tail = src.head + Vector((0, 0.1, 0))
                eb.use_deform = False
                names.append(cn)

        return names

    def setup_constraints(self, armature_obj, pose_bones):
        for i in range(self.bone_count):
            def_bn = self.def_name(f"{i+1:03d}")
            mch_bn = self.mch_name(f"{i+1:03d}")
            fk_bn = self.ctrl_name(f"FK_{i+1:03d}")

            # MCH ← CTRL
            pb = pose_bones.get(mch_bn)
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}FK"
                c.target = armature_obj
                c.subtarget = fk_bn

            # DEF ← MCH
            pb = pose_bones.get(def_bn)
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}Copy"
                c.target = armature_obj
                c.subtarget = mch_bn

    def get_connection_points(self):
        return {
            "root": self.def_name("001"),
            "hip": self.def_name("001"),
            "chest": self.def_name(f"{self.bone_count:03d}"),
            "mid": self.def_name(f"{self.bone_count // 2 + 1:03d}"),
        }

    def get_ui_properties(self):
        props = []
        if self.ik_spline:
            props.append({"name": "spine_ik_fk", "type": "float",
                          "default": 0.0, "min": 0.0, "max": 1.0,
                          "description": "Spine IK/FK blend"})
        return props
