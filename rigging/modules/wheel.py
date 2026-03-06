"""Wheel rig module — three-tier (CTRL → MCH → DEF) wheel with rotation.

Fixed architecture:

    CTRL-Position (steering/placement)
       |
       +-- CTRL-Rotation (manual rotation override)
       |      |
       |      +-- MCH-Wheel (copies rotation from CTRL-Rotation)
       |
       +-- MCH-Axle (copies location from CTRL-Position)

    DEF-Axle   <-- COPY_TRANSFORMS -- MCH-Axle
    DEF-Wheel  <-- COPY_TRANSFORMS -- MCH-Wheel

MCH bones are parented to their respective CTRLs.
CTRL-Position inherits axle's skeleton parent.
"""

from mathutils import Vector
from math import pi
from ..module_base import RigModule
from . import register_module

_CON_PREFIX = "BT_Wheel_"


@register_module
class WheelModule(RigModule):
    module_type = "wheel"
    display_name = "Wheel"
    category = "mechanical"

    def __init__(self, config):
        super().__init__(config)
        self.radius = self.options.get("radius", 0.3)

    def get_bone_slots(self):
        return [
            ("Axle", "Wheel axle bone"),
            ("Wheel", "Wheel rotation bone"),
        ]

    def create_bones(self, armature, edit_bones):
        names = []
        pos = Vector(self.position)

        axle_mapped = self.mapped_bone("Axle")
        wheel_mapped = self.mapped_bone("Wheel")
        axle_src = axle_mapped and edit_bones.get(axle_mapped)
        wheel_src = wheel_mapped and edit_bones.get(wheel_mapped)

        # --- DEF layer ---
        if not axle_mapped:
            bn = self.def_name("Axle")
            eb = edit_bones.new(bn)
            eb.head = pos
            side_dir = Vector((0.05 if self.side == "L" else -0.05, 0, 0))
            eb.tail = pos + side_dir
            eb.use_deform = True
            names.append(bn)

        if not wheel_mapped:
            bn = self.def_name("Wheel")
            eb = edit_bones.new(bn)
            eb.head = pos
            eb.tail = pos + Vector((0, self.radius, 0))
            eb.use_deform = True
            names.append(bn)

        # Determine axle position
        if axle_src:
            axle_pos = axle_src.head.copy()
        else:
            axle_pos = pos.copy()

        # --- CTRL layer ---
        cn = self.ctrl_name("Position")
        eb = edit_bones.new(cn)
        eb.head = axle_pos + Vector((0, 0, self.radius + 0.05))
        eb.tail = axle_pos + Vector((0, 0, self.radius + 0.1))
        eb.use_deform = False
        if axle_src and axle_src.parent:
            eb.parent = axle_src.parent
        names.append(cn)

        cn = self.ctrl_name("Rotation")
        eb = edit_bones.new(cn)
        eb.head = axle_pos
        eb.tail = axle_pos + Vector((0, 0.05, 0))
        eb.use_deform = False
        eb.parent = edit_bones[self.ctrl_name("Position")]
        names.append(cn)

        # --- MCH layer: parented to CTRLs ---
        mn = self.mch_name("Axle")
        eb = edit_bones.new(mn)
        if axle_src:
            eb.head = axle_src.head.copy()
            eb.tail = axle_src.tail.copy()
            eb.roll = axle_src.roll
        else:
            eb.head = pos
            side_dir = Vector((0.05 if self.side == "L" else -0.05, 0, 0))
            eb.tail = pos + side_dir
        eb.use_deform = False
        eb.parent = edit_bones[self.ctrl_name("Position")]
        names.append(mn)

        mn = self.mch_name("Wheel")
        eb = edit_bones.new(mn)
        if wheel_src:
            eb.head = wheel_src.head.copy()
            eb.tail = wheel_src.tail.copy()
            eb.roll = wheel_src.roll
        else:
            eb.head = pos
            eb.tail = pos + Vector((0, self.radius, 0))
        eb.use_deform = False
        eb.parent = edit_bones[self.ctrl_name("Rotation")]
        names.append(mn)

        return names

    def _get_def(self, role):
        return self.mapped_bone(role) or self.def_name(role)

    def setup_constraints(self, armature_obj, pose_bones):
        axle_def = self._get_def("Axle")
        wheel_def = self._get_def("Wheel")
        axle_mch = self.mch_name("Axle")
        wheel_mch = self.mch_name("Wheel")
        pos_ctrl = self.ctrl_name("Position")
        rot_ctrl = self.ctrl_name("Rotation")

        # --- MCH ← CTRL ---
        pb = pose_bones.get(axle_mch)
        if pb:
            c = pb.constraints.new('COPY_LOCATION')
            c.name = f"{_CON_PREFIX}AxlePos"
            c.target = armature_obj
            c.subtarget = pos_ctrl

        pb = pose_bones.get(wheel_mch)
        if pb:
            c = pb.constraints.new('COPY_ROTATION')
            c.name = f"{_CON_PREFIX}WheelRot"
            c.target = armature_obj
            c.subtarget = rot_ctrl

        # --- DEF ← MCH ---
        pb = pose_bones.get(axle_def)
        if pb:
            c = pb.constraints.new('COPY_TRANSFORMS')
            c.name = f"{_CON_PREFIX}AxleCopy"
            c.target = armature_obj
            c.subtarget = axle_mch

        pb = pose_bones.get(wheel_def)
        if pb:
            c = pb.constraints.new('COPY_TRANSFORMS')
            c.name = f"{_CON_PREFIX}WheelCopy"
            c.target = armature_obj
            c.subtarget = wheel_mch

    def get_connection_points(self):
        return {
            "root": self.mch_name("Axle"),
            "axle": self.mch_name("Axle"),
            "wheel": self.mch_name("Wheel"),
        }
