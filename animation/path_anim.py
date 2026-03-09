"""Follow curve animation with banking."""



def setup_follow_path(obj, curve_obj, duration=100, use_banking=True, bank_amount=1.0):
    """Set up an object to follow a curve path.

    Args:
        obj: Object to animate.
        curve_obj: Curve object to follow.
        duration: Animation duration in frames.
        use_banking: Enable banking/tilting on curves.
        bank_amount: Banking multiplier.
    """
    # Add follow path constraint
    constraint = obj.constraints.new('FOLLOW_PATH')
    constraint.target = curve_obj
    constraint.use_fixed_location = True
    constraint.use_curve_follow = True

    if use_banking:
        constraint.use_curve_follow = True
        # Banking is controlled via curve tilt

    # Animate offset
    from ..core.utils import create_fcurve
    create_fcurve(
        obj,
        f"{obj.name}_PathFollow",
        f'constraints["{constraint.name}"].offset_factor',
        0,
        [(1, 0.0), (duration, 1.0)],
    )

    # Set curve path duration
    curve_obj.data.path_duration = duration

    return constraint


def add_curve_tilt_banking(curve_obj, amount=1.0):
    """Add tilt to curve spline points for banking effect.

    Calculates tilt based on curvature direction changes.

    Args:
        curve_obj: The curve object.
        amount: Banking multiplier (radians).
    """
    for spline in curve_obj.data.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points

        for i, point in enumerate(points):
            if i == 0 or i >= len(points) - 1:
                point.tilt = 0.0
                continue

            # Estimate curvature from point positions
            if spline.type == 'BEZIER':
                p_prev = points[i - 1].co
                p_curr = point.co
                p_next = points[i + 1].co
            else:
                p_prev = points[i - 1].co.xyz
                p_curr = point.co.xyz
                p_next = points[i + 1].co.xyz

            v1 = (p_curr - p_prev).normalized()
            v2 = (p_next - p_curr).normalized()

            # Cross product Y component indicates turn direction
            cross_y = v1.x * v2.z - v1.z * v2.x
            point.tilt = cross_y * amount
