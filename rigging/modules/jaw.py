"""Jaw rig module — three-tier (CTRL -> MCH -> DEF) simple hinge for mouth/jaw."""

from mathutils import Vector
from ..module_base import RigModule
from . import register_module

_CON_PREFIX = "BT_Jaw_"


@register_module
class JawModule(RigModule):
    module_type = "jaw"
    display_name = "Jaw"
    category = "organic"

    def __init__(self, config):
        super().__init__(config)
        self.has_upper = self.options.get("upper_jaw", False)

    def create_bones(self, armature, edit_bones):
        names = []
        pos = Vector(self.position)

        # --- DEF layer ---
        bn = self.def_name("Lower")
        eb = edit_bones.new(bn)
        eb.head = pos
        eb.tail = pos + Vector((0, -0.1, -0.02))
        eb.use_deform = True
        names.append(bn)

        if self.has_upper:
            bn = self.def_name("Upper")
            eb = edit_bones.new(bn)
            eb.head = pos
            eb.tail = pos + Vector((0, -0.1, 0.02))
            eb.use_deform = True
            names.append(bn)

        # --- MCH layer ---
        mn = self.mch_name("Lower")
        eb = edit_bones.new(mn)
        src = edit_bones[self.def_name("Lower")]
        eb.head = src.head.copy()
        eb.tail = src.tail.copy()
        eb.use_deform = False
        names.append(mn)

        if self.has_upper:
            mn = self.mch_name("Upper")
            eb = edit_bones.new(mn)
            src = edit_bones[self.def_name("Upper")]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            names.append(mn)

        # --- CTRL layer ---
        cn = self.ctrl_name("Jaw")
        eb = edit_bones.new(cn)
        eb.head = pos + Vector((0, -0.12, -0.03))
        eb.tail = pos + Vector((0, -0.17, -0.03))
        eb.use_deform = False
        names.append(cn)

        if self.has_upper:
            cn = self.ctrl_name("UpperJaw")
            eb = edit_bones.new(cn)
            eb.head = pos + Vector((0, -0.12, 0.03))
            eb.tail = pos + Vector((0, -0.17, 0.03))
            eb.use_deform = False
            names.append(cn)

        return names

    def setup_constraints(self, armature_obj, pose_bones):
        # MCH Lower <- CTRL Jaw
        pb = pose_bones.get(self.mch_name("Lower"))
        if pb:
            c = pb.constraints.new('COPY_TRANSFORMS')
            c.name = f"{_CON_PREFIX}FK"
            c.target = armature_obj
            c.subtarget = self.ctrl_name("Jaw")

        # DEF Lower <- MCH Lower
        pb = pose_bones.get(self.def_name("Lower"))
        if pb:
            c = pb.constraints.new('COPY_TRANSFORMS')
            c.name = f"{_CON_PREFIX}Copy"
            c.target = armature_obj
            c.subtarget = self.mch_name("Lower")

        if self.has_upper:
            # MCH Upper <- CTRL UpperJaw
            pb = pose_bones.get(self.mch_name("Upper"))
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}FK"
                c.target = armature_obj
                c.subtarget = self.ctrl_name("UpperJaw")

            # DEF Upper <- MCH Upper
            pb = pose_bones.get(self.def_name("Upper"))
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}Copy"
                c.target = armature_obj
                c.subtarget = self.mch_name("Upper")

    def get_connection_points(self):
        points = {
            "root": self.def_name("Lower"),
            "jaw": self.def_name("Lower"),
        }
        if self.has_upper:
            points["upper_jaw"] = self.def_name("Upper")
        return points
