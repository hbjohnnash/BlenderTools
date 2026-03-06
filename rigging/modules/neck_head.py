"""Neck + Head rig module — three-tier (CTRL -> MCH -> DEF) FK chain."""

from mathutils import Vector
from ..module_base import RigModule
from . import register_module

_CON_PREFIX = "BT_NeckHead_"


@register_module
class NeckHeadModule(RigModule):
    module_type = "neck_head"
    display_name = "Neck & Head"
    category = "organic"

    def __init__(self, config):
        super().__init__(config)
        self.neck_bones = self.options.get("neck_bones", 2)

    def create_bones(self, armature, edit_bones):
        names = []
        pos = Vector(self.position)
        spacing = 0.1

        # --- DEF layer ---
        for i in range(self.neck_bones):
            bn = self.def_name(f"Neck_{i+1:02d}")
            eb = edit_bones.new(bn)
            eb.head = pos + Vector((0, 0, spacing * i))
            eb.tail = pos + Vector((0, 0, spacing * (i + 1)))
            eb.use_deform = True
            if i > 0:
                eb.parent = edit_bones[self.def_name(f"Neck_{i:02d}")]
                eb.use_connect = True
            names.append(bn)

        head_base = pos + Vector((0, 0, spacing * self.neck_bones))
        bn = self.def_name("Head")
        eb = edit_bones.new(bn)
        eb.head = head_base
        eb.tail = head_base + Vector((0, 0, 0.2))
        eb.use_deform = True
        eb.parent = edit_bones[self.def_name(f"Neck_{self.neck_bones:02d}")]
        eb.use_connect = True
        names.append(bn)

        # --- MCH layer ---
        for i in range(self.neck_bones):
            mn = self.mch_name(f"Neck_{i+1:02d}")
            eb = edit_bones.new(mn)
            src = edit_bones[self.def_name(f"Neck_{i+1:02d}")]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            if i > 0:
                eb.parent = edit_bones[self.mch_name(f"Neck_{i:02d}")]
                eb.use_connect = True
            names.append(mn)

        mn = self.mch_name("Head")
        eb = edit_bones.new(mn)
        src = edit_bones[self.def_name("Head")]
        eb.head = src.head.copy()
        eb.tail = src.tail.copy()
        eb.use_deform = False
        eb.parent = edit_bones[self.mch_name(f"Neck_{self.neck_bones:02d}")]
        eb.use_connect = True
        names.append(mn)

        # --- CTRL layer ---
        for i in range(self.neck_bones):
            cn = self.ctrl_name(f"FK_Neck_{i+1:02d}")
            eb = edit_bones.new(cn)
            src = edit_bones[self.def_name(f"Neck_{i+1:02d}")]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            if i > 0:
                eb.parent = edit_bones[self.ctrl_name(f"FK_Neck_{i:02d}")]
            names.append(cn)

        cn = self.ctrl_name("Head")
        eb = edit_bones.new(cn)
        src = edit_bones[self.def_name("Head")]
        eb.head = src.head.copy()
        eb.tail = src.tail.copy()
        eb.use_deform = False
        eb.parent = edit_bones[self.ctrl_name(f"FK_Neck_{self.neck_bones:02d}")]
        names.append(cn)

        return names

    def setup_constraints(self, armature_obj, pose_bones):
        # Neck bones
        for i in range(self.neck_bones):
            def_bn = self.def_name(f"Neck_{i+1:02d}")
            mch_bn = self.mch_name(f"Neck_{i+1:02d}")
            fk_bn = self.ctrl_name(f"FK_Neck_{i+1:02d}")

            # MCH <- CTRL
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

        # Head bone
        def_bn = self.def_name("Head")
        mch_bn = self.mch_name("Head")
        ctrl_bn = self.ctrl_name("Head")

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
            "root": self.def_name("Neck_01"),
            "neck_base": self.def_name("Neck_01"),
            "head": self.def_name("Head"),
        }
