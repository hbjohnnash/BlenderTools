"""Tail rig module — three-tier (CTRL -> MCH -> DEF) FK chain with optional IK tip."""

from mathutils import Vector

from ..module_base import RigModule
from . import register_module

_CON_PREFIX = "BT_Tail_"


@register_module
class TailModule(RigModule):
    module_type = "tail"
    display_name = "Tail"
    category = "organic"

    def __init__(self, config):
        super().__init__(config)
        self.bone_count = self.options.get("bone_count", 6)
        self.ik_tip = self.options.get("ik_tip", False)
        self.curl = self.options.get("curl", True)

    def create_bones(self, armature, edit_bones):
        names = []
        pos = Vector(self.position)
        direction = Vector(self.options.get("direction", [0, 1, -0.2])).normalized()
        segment_len = self.options.get("segment_length", 0.1)

        # --- DEF layer ---
        for i in range(self.bone_count):
            bn = self.def_name(f"{i+1:03d}")
            eb = edit_bones.new(bn)
            eb.head = pos + direction * segment_len * i
            eb.tail = pos + direction * segment_len * (i + 1)
            eb.use_deform = True
            if i > 0:
                eb.parent = edit_bones[self.def_name(f"{i:03d}")]
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
                eb.parent = edit_bones[self.ctrl_name(f"FK_{i:03d}")]
            names.append(cn)

        # IK tip control
        if self.ik_tip:
            cn = self.ctrl_name("IK_Tip")
            last = edit_bones[self.def_name(f"{self.bone_count:03d}")]
            eb = edit_bones.new(cn)
            eb.head = last.tail.copy()
            eb.tail = last.tail + Vector((0, 0, 0.05))
            eb.use_deform = False
            names.append(cn)

        return names

    def setup_constraints(self, armature_obj, pose_bones):
        for i in range(self.bone_count):
            def_bn = self.def_name(f"{i+1:03d}")
            mch_bn = self.mch_name(f"{i+1:03d}")
            fk_bn = self.ctrl_name(f"FK_{i+1:03d}")

            # MCH <- CTRL (FK)
            pb = pose_bones.get(mch_bn)
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}FK"
                c.target = armature_obj
                c.subtarget = fk_bn

            # DEF <- MCH
            pb = pose_bones.get(def_bn)
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}Copy"
                c.target = armature_obj
                c.subtarget = mch_bn

        # IK on MCH (disabled by default)
        if self.ik_tip:
            pb = pose_bones.get(self.mch_name(f"{self.bone_count:03d}"))
            if pb:
                ik = pb.constraints.new('IK')
                ik.name = f"{_CON_PREFIX}IK"
                ik.target = armature_obj
                ik.subtarget = self.ctrl_name("IK_Tip")
                ik.chain_count = self.bone_count
                ik.influence = 0.0

    def get_connection_points(self):
        return {
            "root": self.def_name("001"),
            "base": self.def_name("001"),
            "tip": self.def_name(f"{self.bone_count:03d}"),
        }
