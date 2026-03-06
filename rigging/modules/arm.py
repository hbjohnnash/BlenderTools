"""Arm rig module — three-tier (CTRL -> MCH -> DEF) IK/FK with optional clavicle and twist bones."""

from mathutils import Vector
from ..module_base import RigModule
from . import register_module

_CON_PREFIX = "BT_Arm_"


@register_module
class ArmModule(RigModule):
    module_type = "arm"
    display_name = "Arm"
    category = "organic"

    def __init__(self, config):
        super().__init__(config)
        self.twist_bones = self.options.get("twist_bones", 1)
        self.clavicle = self.options.get("clavicle", True)

    # ------------------------------------------------------------------
    # Bone creation
    # ------------------------------------------------------------------

    def create_bones(self, armature, edit_bones):
        names = []
        pos = Vector(self.position)
        side_offset = 0.2 if self.side == "L" else -0.2

        # Shared geometry for the main chain
        upper_head = pos + Vector((side_offset, 0, 0))
        upper_tail = pos + Vector((side_offset * 2.5, 0, -0.05))
        lower_tail = upper_tail + Vector((side_offset * 2.0, 0.02, -0.05))
        hand_tail = lower_tail + Vector((side_offset * 0.5, 0, 0))

        # ============================================================
        # DEF layer — deform bones (use_deform=True)
        # ============================================================

        # Clavicle DEF
        if self.clavicle:
            bn = self.def_name("Clavicle")
            eb = edit_bones.new(bn)
            eb.head = pos
            eb.tail = upper_head
            eb.use_deform = True
            names.append(bn)

        # Upper DEF
        bn = self.def_name("Upper")
        eb = edit_bones.new(bn)
        eb.head = upper_head
        eb.tail = upper_tail
        eb.use_deform = True
        if self.clavicle:
            eb.parent = edit_bones[self.def_name("Clavicle")]
            eb.use_connect = True
        names.append(bn)

        # Lower DEF
        bn = self.def_name("Lower")
        eb = edit_bones.new(bn)
        eb.head = upper_tail
        eb.tail = lower_tail
        eb.use_deform = True
        eb.parent = edit_bones[self.def_name("Upper")]
        eb.use_connect = True
        names.append(bn)

        # Hand DEF
        bn = self.def_name("Hand")
        eb = edit_bones.new(bn)
        eb.head = lower_tail
        eb.tail = hand_tail
        eb.use_deform = True
        eb.parent = edit_bones[self.def_name("Lower")]
        eb.use_connect = True
        names.append(bn)

        # Twist DEFs
        for t in range(self.twist_bones):
            bn = self.def_name(f"Twist_Upper_{t+1:02d}")
            src = edit_bones[self.def_name("Upper")]
            eb = edit_bones.new(bn)
            frac = (t + 1) / (self.twist_bones + 1)
            eb.head = src.head.lerp(src.tail, frac)
            eb.tail = src.head.lerp(src.tail, frac + 0.05)
            eb.use_deform = True
            eb.parent = edit_bones[self.def_name("Upper")]
            names.append(bn)

        # ============================================================
        # MCH layer — mechanism bones (use_deform=False)
        # Mirror DEF positions.  Rig constraints live here.
        # ============================================================

        # Clavicle MCH
        if self.clavicle:
            mn = self.mch_name("Clavicle")
            eb = edit_bones.new(mn)
            src = edit_bones[self.def_name("Clavicle")]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            names.append(mn)

        # Main chain MCH
        for part in ("Upper", "Lower", "Hand"):
            mn = self.mch_name(part)
            eb = edit_bones.new(mn)
            src = edit_bones[self.def_name(part)]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            names.append(mn)

        # MCH parenting
        if self.clavicle:
            edit_bones[self.mch_name("Upper")].parent = edit_bones[self.mch_name("Clavicle")]
            edit_bones[self.mch_name("Upper")].use_connect = True
        edit_bones[self.mch_name("Lower")].parent = edit_bones[self.mch_name("Upper")]
        edit_bones[self.mch_name("Lower")].use_connect = True
        edit_bones[self.mch_name("Hand")].parent = edit_bones[self.mch_name("Lower")]
        edit_bones[self.mch_name("Hand")].use_connect = True

        # ============================================================
        # CTRL layer — control bones (use_deform=False)
        # ============================================================

        # Clavicle CTRL
        if self.clavicle:
            cn = self.ctrl_name("Clavicle")
            eb = edit_bones.new(cn)
            src = edit_bones[self.def_name("Clavicle")]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            names.append(cn)

        # FK controls
        for part in ("Upper", "Lower", "Hand"):
            cn = self.ctrl_name(f"FK_{part}")
            eb = edit_bones.new(cn)
            src = edit_bones[self.def_name(part)]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            names.append(cn)

        # FK chain parenting
        edit_bones[self.ctrl_name("FK_Lower")].parent = edit_bones[self.ctrl_name("FK_Upper")]
        edit_bones[self.ctrl_name("FK_Hand")].parent = edit_bones[self.ctrl_name("FK_Lower")]

        # IK target
        cn = self.ctrl_name("IK_Target")
        eb = edit_bones.new(cn)
        eb.head = lower_tail
        eb.tail = lower_tail + Vector((0, 0.1, 0))
        eb.use_deform = False
        names.append(cn)

        # IK pole
        cn = self.ctrl_name("IK_Pole")
        eb = edit_bones.new(cn)
        pole_pos = (upper_head + lower_tail) / 2 + Vector((0, -0.3, 0))
        eb.head = pole_pos
        eb.tail = pole_pos + Vector((0, 0, 0.05))
        eb.use_deform = False
        names.append(cn)

        return names

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    def setup_constraints(self, armature_obj, pose_bones):
        # ==============================================================
        # MCH <- CTRL   (rig logic lives on MCH bones)
        # ==============================================================

        # Clavicle: MCH <- CTRL
        if self.clavicle:
            pb = pose_bones.get(self.mch_name("Clavicle"))
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}Clavicle_FK"
                c.target = armature_obj
                c.subtarget = self.ctrl_name("Clavicle")

        # FK: MCH <- CTRL-FK (toggled)
        for part in ("Upper", "Lower", "Hand"):
            pb = pose_bones.get(self.mch_name(part))
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}FK"
                c.target = armature_obj
                c.subtarget = self.ctrl_name(f"FK_{part}")
                c.influence = 0.0  # IK by default

        # IK: MCH-Lower <- IK target/pole
        pb = pose_bones.get(self.mch_name("Lower"))
        if pb:
            ik = pb.constraints.new('IK')
            ik.name = f"{_CON_PREFIX}IK"
            ik.target = armature_obj
            ik.subtarget = self.ctrl_name("IK_Target")
            ik.pole_target = armature_obj
            ik.pole_subtarget = self.ctrl_name("IK_Pole")
            ik.pole_angle = 0.0
            ik.chain_count = 2

        # Hand rotation from IK target (on MCH)
        pb = pose_bones.get(self.mch_name("Hand"))
        if pb:
            c = pb.constraints.new('COPY_ROTATION')
            c.name = f"{_CON_PREFIX}IK_Rot"
            c.target = armature_obj
            c.subtarget = self.ctrl_name("IK_Target")

        # ==============================================================
        # DEF <- MCH   (clean copy, always influence=1.0)
        # ==============================================================

        # Clavicle: DEF <- MCH
        if self.clavicle:
            pb = pose_bones.get(self.def_name("Clavicle"))
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}Copy"
                c.target = armature_obj
                c.subtarget = self.mch_name("Clavicle")

        # Main chain: DEF <- MCH
        for part in ("Upper", "Lower", "Hand"):
            pb = pose_bones.get(self.def_name(part))
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}Copy"
                c.target = armature_obj
                c.subtarget = self.mch_name(part)

    # ------------------------------------------------------------------
    # Connection points & UI
    # ------------------------------------------------------------------

    def get_connection_points(self):
        points = {
            "root": self.def_name("Upper"),
            "shoulder": self.def_name("Upper"),
            "hand": self.def_name("Hand"),
            "wrist": self.def_name("Hand"),
        }
        if self.clavicle:
            points["clavicle"] = self.def_name("Clavicle")
        return points

    def get_ui_properties(self):
        return [
            {"name": f"arm_{self.side}_ik_fk", "type": "float",
             "default": 1.0, "min": 0.0, "max": 1.0,
             "description": f"Arm {self.side} IK/FK blend (1=IK, 0=FK)"},
        ]
