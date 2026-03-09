"""Wing rig module — three-tier (CTRL -> MCH -> DEF) multi-segment with feather bones."""

from mathutils import Vector

from ..module_base import RigModule
from . import register_module

_CON_PREFIX = "BT_Wing_"


@register_module
class WingModule(RigModule):
    module_type = "wing"
    display_name = "Wing"
    category = "organic"

    def __init__(self, config):
        super().__init__(config)
        self.segments = self.options.get("segments", 3)
        self.feather_bones = self.options.get("feather_bones", 3)

    def create_bones(self, armature, edit_bones):
        names = []
        pos = Vector(self.position)
        side_offset = 0.2 if self.side == "L" else -0.2
        seg_len = 0.3

        # --- DEF layer: main segments ---
        for i in range(self.segments):
            bn = self.def_name(f"Segment_{i+1:02d}")
            eb = edit_bones.new(bn)
            eb.head = pos + Vector((side_offset * (i + 1) * seg_len, 0, 0))
            eb.tail = pos + Vector((side_offset * (i + 2) * seg_len, 0, 0))
            eb.use_deform = True
            if i > 0:
                eb.parent = edit_bones[self.def_name(f"Segment_{i:02d}")]
                eb.use_connect = True
            names.append(bn)

        # --- DEF layer: feather bones ---
        for i in range(self.segments):
            seg = edit_bones[self.def_name(f"Segment_{i+1:02d}")]
            for f in range(self.feather_bones):
                bn = self.def_name(f"Feather_{i+1:02d}_{f+1:02d}")
                eb = edit_bones.new(bn)
                frac = f / max(self.feather_bones - 1, 1)
                base = seg.head.lerp(seg.tail, frac)
                eb.head = base
                eb.tail = base + Vector((0, -0.15, -0.05))
                eb.use_deform = True
                eb.parent = seg
                names.append(bn)

        # --- MCH layer: main segments ---
        for i in range(self.segments):
            mn = self.mch_name(f"Segment_{i+1:02d}")
            eb = edit_bones.new(mn)
            src = edit_bones[self.def_name(f"Segment_{i+1:02d}")]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            if i > 0:
                prev = self.mch_name(f"Segment_{i:02d}")
                eb.parent = edit_bones[prev]
                eb.use_connect = True
            names.append(mn)

        # --- MCH layer: feather bones ---
        for i in range(self.segments):
            mch_seg = edit_bones[self.mch_name(f"Segment_{i+1:02d}")]
            for f in range(self.feather_bones):
                mn = self.mch_name(f"Feather_{i+1:02d}_{f+1:02d}")
                eb = edit_bones.new(mn)
                src = edit_bones[self.def_name(f"Feather_{i+1:02d}_{f+1:02d}")]
                eb.head = src.head.copy()
                eb.tail = src.tail.copy()
                eb.use_deform = False
                eb.parent = mch_seg
                names.append(mn)

        # --- CTRL layer ---
        for i in range(self.segments):
            cn = self.ctrl_name(f"FK_{i+1:02d}")
            eb = edit_bones.new(cn)
            src = edit_bones[self.def_name(f"Segment_{i+1:02d}")]
            eb.head = src.head.copy()
            eb.tail = src.tail.copy()
            eb.use_deform = False
            if i > 0:
                eb.parent = edit_bones[self.ctrl_name(f"FK_{i:02d}")]
            names.append(cn)

        return names

    def setup_constraints(self, armature_obj, pose_bones):
        # --- MCH segments <- CTRL FK ---
        for i in range(self.segments):
            mch_bn = self.mch_name(f"Segment_{i+1:02d}")
            fk_bn = self.ctrl_name(f"FK_{i+1:02d}")

            pb = pose_bones.get(mch_bn)
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}FK"
                c.target = armature_obj
                c.subtarget = fk_bn

        # --- DEF segments <- MCH segments ---
        for i in range(self.segments):
            def_bn = self.def_name(f"Segment_{i+1:02d}")
            mch_bn = self.mch_name(f"Segment_{i+1:02d}")

            pb = pose_bones.get(def_bn)
            if pb:
                c = pb.constraints.new('COPY_TRANSFORMS')
                c.name = f"{_CON_PREFIX}Copy"
                c.target = armature_obj
                c.subtarget = mch_bn

        # --- DEF feathers <- MCH feathers ---
        for i in range(self.segments):
            for f in range(self.feather_bones):
                def_bn = self.def_name(f"Feather_{i+1:02d}_{f+1:02d}")
                mch_bn = self.mch_name(f"Feather_{i+1:02d}_{f+1:02d}")

                pb = pose_bones.get(def_bn)
                if pb:
                    c = pb.constraints.new('COPY_TRANSFORMS')
                    c.name = f"{_CON_PREFIX}Copy"
                    c.target = armature_obj
                    c.subtarget = mch_bn

    def get_connection_points(self):
        return {
            "root": self.def_name("Segment_01"),
            "base": self.def_name("Segment_01"),
            "tip": self.def_name(f"Segment_{self.segments:02d}"),
        }
