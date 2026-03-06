"""Eye rig module — three-tier (CTRL -> MCH -> DEF) aim-based eye with optional eyelid bones."""

from mathutils import Vector
from ..module_base import RigModule
from . import register_module

_CON_PREFIX = "BT_Eye_"


@register_module
class EyeModule(RigModule):
    module_type = "eye"
    display_name = "Eye"
    category = "organic"

    def __init__(self, config):
        super().__init__(config)
        self.eyelids = self.options.get("eyelids", True)
        self.eye_distance = self.options.get("target_distance", 1.0)

    def create_bones(self, armature, edit_bones):
        names = []
        pos = Vector(self.position)

        # --- DEF layer ---
        bn = self.def_name("Eye")
        eb = edit_bones.new(bn)
        eb.head = pos
        eb.tail = pos + Vector((0, -0.05, 0))
        eb.use_deform = True
        names.append(bn)

        if self.eyelids:
            for lid_name, offset in [("UpperLid", Vector((0, -0.01, 0.02))),
                                      ("LowerLid", Vector((0, -0.01, -0.02)))]:
                bn = self.def_name(lid_name)
                eb = edit_bones.new(bn)
                eb.head = pos + offset
                eb.tail = pos + offset + Vector((0, -0.03, 0))
                eb.use_deform = True
                names.append(bn)

        # --- MCH layer ---
        mn = self.mch_name("Eye")
        eb = edit_bones.new(mn)
        src = edit_bones[self.def_name("Eye")]
        eb.head = src.head.copy()
        eb.tail = src.tail.copy()
        eb.use_deform = False
        names.append(mn)

        if self.eyelids:
            for lid_name in ("UpperLid", "LowerLid"):
                mn = self.mch_name(lid_name)
                eb = edit_bones.new(mn)
                src = edit_bones[self.def_name(lid_name)]
                eb.head = src.head.copy()
                eb.tail = src.tail.copy()
                eb.use_deform = False
                names.append(mn)

        # --- CTRL layer ---
        # Eye aim target
        cn = self.ctrl_name("Target")
        eb = edit_bones.new(cn)
        target_pos = pos + Vector((0, -self.eye_distance, 0))
        eb.head = target_pos
        eb.tail = target_pos + Vector((0, 0, 0.03))
        eb.use_deform = False
        names.append(cn)

        # Eyelid controls
        if self.eyelids:
            for lid_name in ("UpperLid", "LowerLid"):
                cn = self.ctrl_name(lid_name)
                eb = edit_bones.new(cn)
                src = edit_bones[self.def_name(lid_name)]
                eb.head = src.head + Vector((0, -0.05, 0))
                eb.tail = eb.head + Vector((0, 0, 0.02))
                eb.use_deform = False
                names.append(cn)

        return names

    def setup_constraints(self, armature_obj, pose_bones):
        # MCH Eye <- CTRL Target (TRACK_TO)
        pb = pose_bones.get(self.mch_name("Eye"))
        if pb:
            c = pb.constraints.new('TRACK_TO')
            c.name = f"{_CON_PREFIX}Track"
            c.target = armature_obj
            c.subtarget = self.ctrl_name("Target")
            c.track_axis = 'TRACK_NEGATIVE_Y'
            c.up_axis = 'UP_Z'

        # DEF Eye <- MCH Eye
        pb = pose_bones.get(self.def_name("Eye"))
        if pb:
            c = pb.constraints.new('COPY_TRANSFORMS')
            c.name = f"{_CON_PREFIX}Copy"
            c.target = armature_obj
            c.subtarget = self.mch_name("Eye")

        # Eyelids
        if self.eyelids:
            for lid_name in ("UpperLid", "LowerLid"):
                # MCH lid <- CTRL lid
                pb = pose_bones.get(self.mch_name(lid_name))
                if pb:
                    c = pb.constraints.new('COPY_TRANSFORMS')
                    c.name = f"{_CON_PREFIX}FK"
                    c.target = armature_obj
                    c.subtarget = self.ctrl_name(lid_name)

                # DEF lid <- MCH lid
                pb = pose_bones.get(self.def_name(lid_name))
                if pb:
                    c = pb.constraints.new('COPY_TRANSFORMS')
                    c.name = f"{_CON_PREFIX}Copy"
                    c.target = armature_obj
                    c.subtarget = self.mch_name(lid_name)

    def get_connection_points(self):
        return {
            "root": self.def_name("Eye"),
            "eye": self.def_name("Eye"),
        }
