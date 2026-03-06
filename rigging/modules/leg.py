"""Leg rig module — three-tier (CTRL -> MCH -> DEF) IK/FK with optional twist bones."""

from mathutils import Vector
from ..module_base import RigModule
from . import register_module

_CON_PREFIX = "BT_Leg_"

_CHAIN_PARTS = ("Thigh", "Shin", "Foot", "Toe")


@register_module
class LegModule(RigModule):
    module_type = "leg"
    display_name = "Leg"
    category = "organic"

    def __init__(self, config):
        super().__init__(config)
        self.twist_bones = self.options.get("twist_bones", 1)
        self.foot_roll = self.options.get("foot_roll", True)

    def create_bones(self, armature, edit_bones):
        names = []
        pos = Vector(self.position)
        side_offset = 0.1 if self.side == "L" else -0.1

        # ------------------------------------------------------------------ #
        #  Bone positions (shared across all tiers)
        # ------------------------------------------------------------------ #
        thigh_head = pos + Vector((side_offset, 0, 0))
        thigh_tail = thigh_head + Vector((0, 0.02, -0.45))
        shin_tail = thigh_tail + Vector((0, -0.02, -0.45))
        foot_tail = shin_tail + Vector((0, -0.15, -0.05))
        toe_tail = foot_tail + Vector((0, -0.08, 0))

        positions = {
            "Thigh": (thigh_head, thigh_tail),
            "Shin":  (thigh_tail, shin_tail),
            "Foot":  (shin_tail, foot_tail),
            "Toe":   (foot_tail, toe_tail),
        }

        parents_connect = {
            "Shin":  "Thigh",
            "Foot":  "Shin",
            "Toe":   "Foot",
        }

        # ------------------------------------------------------------------ #
        #  DEF layer — deform bones
        # ------------------------------------------------------------------ #
        for part in _CHAIN_PARTS:
            bn = self.def_name(part)
            head, tail = positions[part]
            eb = edit_bones.new(bn)
            eb.head = head
            eb.tail = tail
            eb.use_deform = True
            parent_part = parents_connect.get(part)
            if parent_part:
                eb.parent = edit_bones[self.def_name(parent_part)]
                eb.use_connect = True
            names.append(bn)

        # ------------------------------------------------------------------ #
        #  MCH layer — mechanism bones (mirror DEF positions)
        # ------------------------------------------------------------------ #
        for part in _CHAIN_PARTS:
            mn = self.mch_name(part)
            src = edit_bones[self.def_name(part)]
            eb = edit_bones.new(mn)
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            parent_part = parents_connect.get(part)
            if parent_part:
                eb.parent = edit_bones[self.mch_name(parent_part)]
                eb.use_connect = True
            names.append(mn)

        # ------------------------------------------------------------------ #
        #  CTRL layer — FK controls
        # ------------------------------------------------------------------ #
        for part in _CHAIN_PARTS:
            cn = self.ctrl_name(f"FK_{part}")
            src = edit_bones[self.def_name(part)]
            eb = edit_bones.new(cn)
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            parent_part = parents_connect.get(part)
            if parent_part:
                eb.parent = edit_bones[self.ctrl_name(f"FK_{parent_part}")]
            names.append(cn)

        # ------------------------------------------------------------------ #
        #  CTRL layer — IK controls
        # ------------------------------------------------------------------ #

        # IK target (foot controller)
        cn = self.ctrl_name("IK_Foot")
        eb = edit_bones.new(cn)
        eb.head = shin_tail
        eb.tail = shin_tail + Vector((0, -0.15, 0))
        eb.use_deform = False
        names.append(cn)

        # IK pole (knee target)
        cn = self.ctrl_name("IK_Pole")
        eb = edit_bones.new(cn)
        pole_pos = (thigh_head + shin_tail) / 2 + Vector((0, -0.4, 0))
        eb.head = pole_pos
        eb.tail = pole_pos + Vector((0, 0, 0.05))
        eb.use_deform = False
        names.append(cn)

        # ------------------------------------------------------------------ #
        #  MCH layer — foot-roll mechanism bones
        # ------------------------------------------------------------------ #
        if self.foot_roll:
            for label, head, tail in [
                ("HeelPivot",
                 shin_tail + Vector((0, 0.05, -foot_tail.z + shin_tail.z)),
                 shin_tail + Vector((0, 0.05, -foot_tail.z + shin_tail.z + 0.05))),
                ("ToePivot", foot_tail, foot_tail + Vector((0, 0, 0.05))),
            ]:
                mn = self.mch_name(label)
                eb = edit_bones.new(mn)
                eb.head = head
                eb.tail = tail
                eb.use_deform = False
                names.append(mn)

        # ------------------------------------------------------------------ #
        #  DEF layer — twist bones (children of DEF-Thigh)
        # ------------------------------------------------------------------ #
        for t in range(self.twist_bones):
            bn = self.def_name(f"Twist_Thigh_{t+1:02d}")
            src = edit_bones[self.def_name("Thigh")]
            eb = edit_bones.new(bn)
            frac = (t + 1) / (self.twist_bones + 1)
            eb.head = src.head.lerp(src.tail, frac)
            eb.tail = src.head.lerp(src.tail, frac + 0.05)
            eb.use_deform = True
            eb.parent = edit_bones[self.def_name("Thigh")]
            names.append(bn)

        return names

    def setup_constraints(self, armature_obj, pose_bones):
        # ------------------------------------------------------------------ #
        #  DEF <- MCH  (clean deform copy)
        # ------------------------------------------------------------------ #
        for part in _CHAIN_PARTS:
            def_bn = self.def_name(part)
            mch_bn = self.mch_name(part)

            pb = pose_bones.get(def_bn)
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}Copy"
                c.target = armature_obj
                c.subtarget = mch_bn

        # ------------------------------------------------------------------ #
        #  MCH <- CTRL  (rig logic lives here)
        # ------------------------------------------------------------------ #

        # FK: MCH copies FK control rotation/position
        for part in _CHAIN_PARTS:
            mch_bn = self.mch_name(part)
            fk_bn = self.ctrl_name(f"FK_{part}")

            pb = pose_bones.get(mch_bn)
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}FK"
                c.target = armature_obj
                c.subtarget = fk_bn
                c.influence = 0.0  # off by default (IK active)

        # IK on MCH-Shin
        pb = pose_bones.get(self.mch_name("Shin"))
        if pb:
            ik = pb.constraints.new('IK')
            ik.name = f"{_CON_PREFIX}IK"
            ik.target = armature_obj
            ik.subtarget = self.ctrl_name("IK_Foot")
            ik.pole_target = armature_obj
            ik.pole_subtarget = self.ctrl_name("IK_Pole")
            ik.pole_angle = 3.14159
            ik.chain_count = 2

        # MCH-Foot copies IK foot rotation (when in IK mode)
        pb = pose_bones.get(self.mch_name("Foot"))
        if pb:
            c = pb.constraints.new('COPY_ROTATION')
            c.name = f"{_CON_PREFIX}IK_Rot"
            c.target = armature_obj
            c.subtarget = self.ctrl_name("IK_Foot")

    def get_connection_points(self):
        return {
            "root": self.def_name("Thigh"),
            "hip": self.def_name("Thigh"),
            "foot": self.def_name("Foot"),
            "toe": self.def_name("Toe"),
        }

    def get_ui_properties(self):
        return [
            {"name": f"leg_{self.side}_ik_fk", "type": "float",
             "default": 1.0, "min": 0.0, "max": 1.0,
             "description": f"Leg {self.side} IK/FK blend"},
        ]
