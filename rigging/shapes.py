"""Control bone custom shape library.

Procedural shape generation for rig controls. Shapes are created as
mesh objects in a hidden 'BT_Shapes' collection and reused via
bone.custom_shape. Sizing uses custom_shape_scale_xyz (no mesh duplication).

Users can extend the library by adding any mesh to the BT_Shapes collection.
"""

from math import cos, pi, sin

import bpy

from ..core.constants import (
    CONTROL_PREFIX,
    WRAP_CTRL_PREFIX,
)

SHAPE_COLLECTION = "BT_Shapes"


# ---------------------------------------------------------------------------
# Collection management
# ---------------------------------------------------------------------------

def _get_or_create_collection():
    col = bpy.data.collections.get(SHAPE_COLLECTION)
    if col is None:
        col = bpy.data.collections.new(SHAPE_COLLECTION)
        bpy.context.scene.collection.children.link(col)
    col.hide_viewport = True
    col.hide_render = True
    return col


def _create_mesh_object(name, verts, edges, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    _get_or_create_collection().objects.link(obj)
    return obj


# ---------------------------------------------------------------------------
# Shape generators
# ---------------------------------------------------------------------------

def _create_circle(name="BT_Shape_Circle", segments=24, radius=0.5):
    verts = []
    edges = []
    for i in range(segments):
        a = 2 * pi * i / segments
        verts.append((cos(a) * radius, 0, sin(a) * radius))
        edges.append((i, (i + 1) % segments))
    return _create_mesh_object(name, verts, edges, [])


def _create_cube(name="BT_Shape_Cube", size=0.5):
    s = size / 2
    verts = [
        (-s, -s, -s), (s, -s, -s), (s, s, -s), (-s, s, -s),
        (-s, -s,  s), (s, -s,  s), (s, s,  s), (-s, s,  s),
    ]
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    return _create_mesh_object(name, verts, edges, [])


def _create_diamond(name="BT_Shape_Diamond", size=0.35):
    s = size
    verts = [
        (0, 0, s), (s, 0, 0), (0, s, 0),
        (-s, 0, 0), (0, -s, 0), (0, 0, -s),
    ]
    faces = [
        (0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1),
        (5, 2, 1), (5, 3, 2), (5, 4, 3), (5, 1, 4),
    ]
    return _create_mesh_object(name, verts, [], faces)


def _create_sphere(name="BT_Shape_Sphere", segments=12, rings=6, radius=0.3):
    verts = [(0, 0, radius)]
    faces = []

    for ring in range(1, rings):
        phi = pi * ring / rings
        for seg in range(segments):
            theta = 2 * pi * seg / segments
            verts.append((
                radius * sin(phi) * cos(theta),
                radius * sin(phi) * sin(theta),
                radius * cos(phi),
            ))

    verts.append((0, 0, -radius))

    # Top cap
    for i in range(segments):
        faces.append((0, i + 1, (i + 1) % segments + 1))

    # Middle rings
    for ring in range(rings - 2):
        for seg in range(segments):
            a = 1 + ring * segments + seg
            b = 1 + ring * segments + (seg + 1) % segments
            c = 1 + (ring + 1) * segments + (seg + 1) % segments
            d = 1 + (ring + 1) * segments + seg
            faces.append((a, b, c, d))

    # Bottom cap
    bottom = len(verts) - 1
    start = 1 + (rings - 2) * segments
    for i in range(segments):
        faces.append((bottom, start + (i + 1) % segments, start + i))

    return _create_mesh_object(name, verts, [], faces)


def _create_arrow(name="BT_Shape_Arrow", length=1.0, width=0.15):
    w = width / 2
    hw = width
    bl = length * 0.7
    verts = [
        (-w, 0, 0), (w, 0, 0), (w, bl, 0), (-w, bl, 0),
        (-hw, bl, 0), (hw, bl, 0), (0, length, 0),
    ]
    faces = [(0, 1, 2, 3), (4, 5, 6)]
    return _create_mesh_object(name, verts, [], faces)


def _create_square(name="BT_Shape_Square", size=0.5):
    s = size / 2
    verts = [(-s, 0, -s), (s, 0, -s), (s, 0, s), (-s, 0, s)]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
    return _create_mesh_object(name, verts, edges, [])


def _create_line(name="BT_Shape_Line", length=1.0):
    verts = [(0, 0, 0), (0, length, 0)]
    edges = [(0, 1)]
    return _create_mesh_object(name, verts, edges, [])


SHAPE_CREATORS = {
    'CIRCLE': _create_circle,
    'CUBE': _create_cube,
    'DIAMOND': _create_diamond,
    'SPHERE': _create_sphere,
    'ARROW': _create_arrow,
    'SQUARE': _create_square,
    'LINE': _create_line,
}


# ---------------------------------------------------------------------------
# Shape access
# ---------------------------------------------------------------------------

def get_shape(shape_type):
    """Get or create a shape mesh object by type name.

    Also supports custom shapes: any mesh in BT_Shapes referenced by name.
    """
    canonical = f"BT_Shape_{shape_type.title()}"

    obj = bpy.data.objects.get(canonical)
    if obj is not None:
        return obj

    # Check BT_Shapes collection for custom names
    col = bpy.data.collections.get(SHAPE_COLLECTION)
    if col:
        for o in col.objects:
            if o.name == shape_type:
                return o

    creator = SHAPE_CREATORS.get(shape_type.upper())
    if creator:
        return creator(name=canonical)

    return None


def list_shapes():
    """Return list of (identifier, display_name) for all available shapes."""
    items = [(k, k.title()) for k in SHAPE_CREATORS]
    col = bpy.data.collections.get(SHAPE_COLLECTION)
    if col:
        for o in col.objects:
            if not o.name.startswith("BT_Shape_"):
                items.append((o.name, o.name))
    return items


def add_custom_shape(mesh_obj):
    """Move a user's mesh object into the shape library collection."""
    col = _get_or_create_collection()
    for c in list(mesh_obj.users_collection):
        c.objects.unlink(mesh_obj)
    col.objects.link(mesh_obj)


# ---------------------------------------------------------------------------
# Shape assignment
# ---------------------------------------------------------------------------

def assign_shape(pose_bone, shape_type, scale=1.0):
    shape_obj = get_shape(shape_type)
    if shape_obj is None:
        return
    pose_bone.custom_shape = shape_obj
    pose_bone.custom_shape_scale_xyz = (scale, scale, scale)
    pose_bone.use_custom_shape_bone_size = True


def _get_cog_fk_names(armature_obj):
    """Find FK CTRL names for COG bones (first bone of spine/root chains).

    These bones need unlocked location for body positioning.
    """
    sd = getattr(armature_obj, 'bt_scan', None)
    if not sd:
        return set()

    cog_names = set()
    for chain in sd.chains:
        if chain.module_type not in ('spine', 'root'):
            continue
        # Find first bone in this chain
        chain_bones = [b for b in sd.bones
                       if b.chain_id == chain.chain_id and not b.skip]
        if chain_bones:
            first = chain_bones[0]
            ctrl_name = f"{WRAP_CTRL_PREFIX}{chain.chain_id}_FK_{first.role}"
            cog_names.add(ctrl_name)
    return cog_names


def assign_shapes_for_wrap_rig(armature_obj):
    """Auto-assign shapes and lock transforms for all wrap rig CTRL bones."""
    cog_bones = _get_cog_fk_names(armature_obj)

    for pbone in armature_obj.pose.bones:
        name = pbone.name
        if not name.startswith(WRAP_CTRL_PREFIX):
            continue

        suffix = name[len(WRAP_CTRL_PREFIX):]

        if name.endswith("_IK_target"):
            assign_shape(pbone, 'CUBE', scale=0.6)
        elif name.endswith("_IK_pole"):
            assign_shape(pbone, 'DIAMOND', scale=0.5)
        elif "_Spline_" in name:
            assign_shape(pbone, 'SPHERE', scale=0.4)
        elif "_FK_" in suffix:
            assign_shape(pbone, 'CIRCLE', scale=0.8)
            # Lock location on FK bones, except COG (hips) which needs translation
            if name not in cog_bones:
                pbone.lock_location = (True, True, True)
        else:
            assign_shape(pbone, 'CIRCLE', scale=0.6)


def assign_shapes_for_modular_rig(armature_obj):
    """Auto-assign shapes to modular rig CTRL bones."""
    for pbone in armature_obj.pose.bones:
        if not pbone.name.startswith(CONTROL_PREFIX):
            continue
        has_ik = any(c.type in ('IK', 'SPLINE_IK') for c in pbone.constraints)
        if has_ik:
            assign_shape(pbone, 'CUBE', scale=0.6)
        else:
            assign_shape(pbone, 'CIRCLE', scale=0.8)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def _shape_items(self, context):
    col = bpy.data.collections.get(SHAPE_COLLECTION)
    custom = []
    if col:
        custom = [
            (o.name, o.name, "Custom shape")
            for o in col.objects
            if not o.name.startswith("BT_Shape_")
        ]
    return [(k, k.title(), "") for k in SHAPE_CREATORS] + custom


class BT_OT_ResizeCtrlBones(bpy.types.Operator):
    bl_idname = "bt.resize_ctrl_bones"
    bl_label = "Resize Control Shapes"
    bl_description = "Scale custom shapes of selected control bones"
    bl_options = {'REGISTER', 'UNDO'}

    scale: bpy.props.FloatProperty(
        name="Scale", default=1.0, min=0.1, max=5.0, step=10,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object and context.active_object.type == 'ARMATURE'
                and context.mode == 'POSE' and context.selected_pose_bones)

    def execute(self, context):
        count = 0
        for pbone in context.selected_pose_bones:
            if pbone.custom_shape:
                pbone.custom_shape_scale_xyz = (self.scale, self.scale, self.scale)
                count += 1
        self.report({'INFO'}, f"Resized {count} bone shapes")
        return {'FINISHED'}

    def invoke(self, context, event):
        if context.selected_pose_bones:
            pb = context.selected_pose_bones[0]
            if pb.custom_shape:
                self.scale = pb.custom_shape_scale_xyz[0]
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_AddCustomShape(bpy.types.Operator):
    bl_idname = "bt.add_custom_shape"
    bl_label = "Add to Shape Library"
    bl_description = "Add the active mesh object to the control shape library"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        add_custom_shape(obj)
        self.report({'INFO'}, f"Added '{obj.name}' to shape library")
        return {'FINISHED'}


class BT_OT_AssignBoneShape(bpy.types.Operator):
    bl_idname = "bt.assign_bone_shape"
    bl_label = "Assign Shape"
    bl_description = "Assign a shape from the library to selected bones"
    bl_options = {'REGISTER', 'UNDO'}

    shape_type: bpy.props.EnumProperty(
        name="Shape", items=_shape_items,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object and context.active_object.type == 'ARMATURE'
                and context.mode == 'POSE' and context.selected_pose_bones)

    def execute(self, context):
        for pbone in context.selected_pose_bones:
            assign_shape(pbone, self.shape_type)
        self.report({'INFO'}, f"Assigned {self.shape_type} to {len(context.selected_pose_bones)} bones")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BT_OT_ClearBoneShapes(bpy.types.Operator):
    bl_idname = "bt.clear_bone_shapes"
    bl_label = "Clear Shapes"
    bl_description = "Remove custom shapes from selected bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.active_object and context.active_object.type == 'ARMATURE'
                and context.mode == 'POSE' and context.selected_pose_bones)

    def execute(self, context):
        for pbone in context.selected_pose_bones:
            pbone.custom_shape = None
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    BT_OT_ResizeCtrlBones,
    BT_OT_AddCustomShape,
    BT_OT_AssignBoneShape,
    BT_OT_ClearBoneShapes,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
