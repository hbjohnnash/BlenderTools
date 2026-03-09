"""Finger chain rig module — three-tier (CTRL -> MCH -> DEF) individual finger with curl controls."""

from mathutils import Vector

from ..module_base import RigModule
from . import register_module

_CON_PREFIX = "BT_Finger_"


@register_module
class FingerChainModule(RigModule):
    module_type = "finger_chain"
    display_name = "Finger Chain"
    category = "organic"

    def __init__(self, config):
        super().__init__(config)
        self.bone_count = self.options.get("bone_count", 3)
        self.finger_name = self.options.get("finger_name", "Index")

    def create_bones(self, armature, edit_bones):
        names = []
        pos = Vector(self.position)
        direction = Vector(self.options.get("direction", [0, -0.03, 0])).normalized()
        seg_len = self.options.get("segment_length", 0.03)

        # --- DEF layer ---
        for i in range(self.bone_count):
            bn = self.def_name(f"{self.finger_name}_{i+1:02d}")
            eb = edit_bones.new(bn)
            eb.head = pos + direction * seg_len * i
            eb.tail = pos + direction * seg_len * (i + 1)
            eb.use_deform = True
            if i > 0:
                eb.parent = edit_bones[self.def_name(f"{self.finger_name}_{i:02d}")]
                eb.use_connect = True
            names.append(bn)

        # --- MCH layer ---
        for i in range(self.bone_count):
            mn = self.mch_name(f"{self.finger_name}_{i+1:02d}")
            eb = edit_bones.new(mn)
            src = edit_bones[self.def_name(f"{self.finger_name}_{i+1:02d}")]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            if i > 0:
                prev = self.mch_name(f"{self.finger_name}_{i:02d}")
                eb.parent = edit_bones[prev]
                eb.use_connect = True
            names.append(mn)

        # --- CTRL layer ---
        for i in range(self.bone_count):
            cn = self.ctrl_name(f"{self.finger_name}_{i+1:02d}")
            eb = edit_bones.new(cn)
            src = edit_bones[self.def_name(f"{self.finger_name}_{i+1:02d}")]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            if i > 0:
                eb.parent = edit_bones[self.ctrl_name(f"{self.finger_name}_{i:02d}")]
            names.append(cn)

        # Master curl control
        cn = self.ctrl_name(f"{self.finger_name}_Curl")
        first = edit_bones[self.def_name(f"{self.finger_name}_01")]
        eb = edit_bones.new(cn)
        eb.head = first.head + Vector((0, 0, 0.02))
        eb.tail = first.head + Vector((0, 0, 0.04))
        eb.use_deform = False
        names.append(cn)

        return names

    def setup_constraints(self, armature_obj, pose_bones):
        for i in range(self.bone_count):
            def_bn = self.def_name(f"{self.finger_name}_{i+1:02d}")
            mch_bn = self.mch_name(f"{self.finger_name}_{i+1:02d}")
            ctrl_bn = self.ctrl_name(f"{self.finger_name}_{i+1:02d}")

            # MCH <- CTRL
            pb = pose_bones.get(mch_bn)
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}FK"
                c.target = armature_obj
                c.subtarget = ctrl_bn

            # DEF <- MCH
            pb = pose_bones.get(def_bn)
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}Copy"
                c.target = armature_obj
                c.subtarget = mch_bn

    def get_connection_points(self):
        return {
            "root": self.def_name(f"{self.finger_name}_01"),
            "base": self.def_name(f"{self.finger_name}_01"),
            "tip": self.def_name(f"{self.finger_name}_{self.bone_count:02d}"),
        }
