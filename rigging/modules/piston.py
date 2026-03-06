"""Piston rig module — three-tier (CTRL → MCH → DEF) mechanical piston.

Fixed architecture:

    CTRL-Base                     CTRL-Target
       |                              |
       +-- MCH-Cylinder --AIM/STR-->  |  (toward Target)
       |                              |
       |  <--AIM/STR-- MCH-Rod -------+  (toward Base)

    DEF-Cylinder  <-- COPY_TRANSFORMS -- MCH-Cylinder
    DEF-Rod       <-- COPY_TRANSFORMS -- MCH-Rod

MCH-Cylinder is parented to CTRL-Base (anchored at base, aims toward target).
MCH-Rod is parented to CTRL-Target (anchored at target, aims toward base).
CTRL-Base is reparented by assembly via parent_bone (the bone initially clicked).
CTRL-Target uses the explicit Rod_Parent mapping, or falls back to rod's skeleton parent.

By default, MCH bones use DAMPED_TRACK (rigid piston — no mesh deformation).
Set stretch_mode option to "cylinder", "rod", or "both" for stretchable parts.

Bone mapping: user maps existing Cylinder and Rod bones. Module always
creates its own CTRL and MCH bones. DEF bones are only created when
no mapping is provided.
"""

from mathutils import Vector
from ..module_base import RigModule
from . import register_module

_CON_PREFIX = "BT_Piston_"


@register_module
class PistonModule(RigModule):
    module_type = "piston"
    display_name = "Piston"
    category = "mechanical"

    def __init__(self, config):
        super().__init__(config)
        self.stroke_length = self.options.get("stroke_length", 0.3)
        # "none" (default): both rigid (DAMPED_TRACK)
        # "cylinder": cylinder stretches, rod rigid
        # "rod": rod stretches, cylinder rigid
        # "both": both stretch (STRETCH_TO)
        self.stretch_mode = self.options.get("stretch_mode", "none")

    def get_bone_slots(self):
        return [
            ("Cylinder", "Outer cylinder (base end)"),
            ("Rod", "Inner sliding rod"),
            ("Rod_Parent", "Bone the rod end mounts to"),
        ]

    def create_bones(self, armature, edit_bones):
        names = []
        pos = Vector(self.position)
        direction = Vector(self.options.get("direction", [0, 0, 1])).normalized()

        cyl_mapped = self.mapped_bone("Cylinder")
        rod_mapped = self.mapped_bone("Rod")
        cyl_src = cyl_mapped and edit_bones.get(cyl_mapped)
        rod_src = rod_mapped and edit_bones.get(rod_mapped)

        # Determine anchor positions from mapped bones or defaults
        if cyl_src:
            base_pos = cyl_src.head.copy()
            cyl_tail = cyl_src.tail.copy()
        else:
            base_pos = pos.copy()
            cyl_tail = pos + direction * self.stroke_length

        if rod_src:
            target_pos = rod_src.head.copy()
            rod_tail = rod_src.tail.copy()
        else:
            target_pos = pos + direction * self.stroke_length * 0.5
            rod_tail = pos + direction * self.stroke_length

        # --- DEF layer: only if not mapped ---
        if not cyl_mapped:
            bn = self.def_name("Cylinder")
            eb = edit_bones.new(bn)
            eb.head = base_pos
            eb.tail = cyl_tail
            eb.use_deform = True
            names.append(bn)

        if not rod_mapped:
            bn = self.def_name("Rod")
            eb = edit_bones.new(bn)
            eb.head = target_pos
            eb.tail = rod_tail
            eb.use_deform = True
            names.append(bn)

        # --- CTRL layer ---
        # CTRL-Base at cylinder anchor
        cn = self.ctrl_name("Base")
        eb = edit_bones.new(cn)
        eb.head = base_pos
        eb.tail = base_pos + Vector((0, 0.05, 0))
        eb.use_deform = False
        if cyl_src and cyl_src.parent:
            eb.parent = cyl_src.parent
        names.append(cn)

        # CTRL-Target at rod anchor — use explicit Rod_Parent if mapped
        cn = self.ctrl_name("Target")
        eb = edit_bones.new(cn)
        eb.head = target_pos
        eb.tail = target_pos + Vector((0, 0.05, 0))
        eb.use_deform = False
        rod_parent_name = self.mapped_bone("Rod_Parent")
        if rod_parent_name:
            rod_parent_eb = edit_bones.get(rod_parent_name)
            if rod_parent_eb:
                eb.parent = rod_parent_eb
        elif rod_src and rod_src.parent:
            eb.parent = rod_src.parent
        names.append(cn)

        # --- MCH layer ---
        # MCH-Cylinder: parented to CTRL-Base
        mn = self.mch_name("Cylinder")
        eb = edit_bones.new(mn)
        if cyl_src:
            eb.head = cyl_src.head.copy()
            eb.tail = cyl_src.tail.copy()
            eb.roll = cyl_src.roll
        else:
            eb.head = base_pos
            eb.tail = cyl_tail
        eb.use_deform = False
        eb.parent = edit_bones[self.ctrl_name("Base")]
        names.append(mn)

        # MCH-Rod: parented to CTRL-Target
        mn = self.mch_name("Rod")
        eb = edit_bones.new(mn)
        if rod_src:
            eb.head = rod_src.head.copy()
            eb.tail = rod_src.tail.copy()
            eb.roll = rod_src.roll
        else:
            eb.head = target_pos
            eb.tail = rod_tail
        eb.use_deform = False
        eb.parent = edit_bones[self.ctrl_name("Target")]
        names.append(mn)

        return names

    def _get_def(self, role):
        return self.mapped_bone(role) or self.def_name(role)

    def _add_aim_constraint(self, pb, armature_obj, subtarget, name, use_stretch):
        """Add DAMPED_TRACK or STRETCH_TO based on stretch mode."""
        if use_stretch:
            c = pb.constraints.new('STRETCH_TO')
            c.name = name
            c.target = armature_obj
            c.subtarget = subtarget
            c.rest_length = 0
            c.bulge = 0
        else:
            c = pb.constraints.new('DAMPED_TRACK')
            c.name = name
            c.target = armature_obj
            c.subtarget = subtarget
            c.track_axis = 'TRACK_Y'

    def setup_constraints(self, armature_obj, pose_bones):
        cyl_def = self._get_def("Cylinder")
        rod_def = self._get_def("Rod")
        cyl_mch = self.mch_name("Cylinder")
        rod_mch = self.mch_name("Rod")
        base_ctrl = self.ctrl_name("Base")
        target_ctrl = self.ctrl_name("Target")

        cyl_stretch = self.stretch_mode in ("cylinder", "both")
        rod_stretch = self.stretch_mode in ("rod", "both")

        # --- MCH: piston mechanics ---
        # Cylinder aims from Base toward Target
        pb = pose_bones.get(cyl_mch)
        if pb:
            self._add_aim_constraint(
                pb, armature_obj, target_ctrl,
                f"{_CON_PREFIX}CylTrack", cyl_stretch,
            )

        # Rod aims from Target toward Base
        pb = pose_bones.get(rod_mch)
        if pb:
            self._add_aim_constraint(
                pb, armature_obj, base_ctrl,
                f"{_CON_PREFIX}RodTrack", rod_stretch,
            )

        # --- DEF ← MCH: clean copy ---
        pb = pose_bones.get(cyl_def)
        if pb:
            c = pb.constraints.new('COPY_TRANSFORMS')
            c.name = f"{_CON_PREFIX}CylCopy"
            c.target = armature_obj
            c.subtarget = cyl_mch

        pb = pose_bones.get(rod_def)
        if pb:
            c = pb.constraints.new('COPY_TRANSFORMS')
            c.name = f"{_CON_PREFIX}RodCopy"
            c.target = armature_obj
            c.subtarget = rod_mch

    def get_connection_points(self):
        return {
            "root": self.ctrl_name("Base"),
            "base": self.ctrl_name("Base"),
            "tip": self.ctrl_name("Target"),
        }
