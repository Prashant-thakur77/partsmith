import cadquery as cq
import math

PARAMS = {
    "body_thickness": (16.0, 10.0, 20.0, 0.5, "mm", False, "Knob height thickness"),
    "bore_dia": (6.0, 4.0, 8.0, 0.1, "mm", True, "D-shaft diameter round side"),
    "bore_flat_depth": (0.75, 0.2, 1.5, 0.05, "mm", True, "D-flat cut depth from outer circle"),
    "bore_depth": (10.0, 6.0, 14.0, 0.5, "mm", False, "Blind D-bore depth from mounting face"),
    "clearance": (0.2, 0.0, 0.5, 0.05, "mm", True, "Radial fit clearance added to bore"),
    "knurl_count": (24, 8, 48, 1, "", False, "Knurl count visual only"),
}

def build(p: dict) -> cq.Workplane:
    th = float(p["body_thickness"])
    bore_dia = float(p["bore_dia"])
    bore_flat_depth = float(p["bore_flat_depth"])
    bore_depth = float(p["bore_depth"])
    clearance = float(p["clearance"])

    pts = [
        (11.16, 10.013),
        (7.746, 12.305),
        (6.378, 13.574),
        (1.725, 14.836),
        (-3.468, 14.824),
        (-7.94, 13.136),
        (-9.07, 12.109),
        (-9.641, 11.881),
        (-11.519, 10.024),
        (-12.389, 8.419),
        (-13.385, 7.362),
        (-14.221, 5.725),
        (-14.647, 3.68),
        (-14.893, -0.475),
        (-14.684, -2.985),
        (-14.081, -5.229),
        (-12.644, -8.3),
        (-8.337, -12.611),
        (-4.742, -14.213),
        (-1.327, -14.825),
        (1.322, -14.833),
        (4.245, -14.401),
        (6.401, -13.803),
        (9.478, -11.953),
        (12.437, -8.948),
        (13.143, -7.809),
        (14.215, -5.09),
        (14.662, -3.271),
        (14.887, 1.123),
        (14.322, 2.909),
        (14.246, 4.05),
        (13.436, 6.493),
        (12.576, 7.456),
    ]

    wp = cq.Workplane("XY").moveTo(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        wp = wp.lineTo(x, y)
    body = wp.close().extrude(th)

    r = (bore_dia + clearance) * 0.5
    flat_dist = r - float(bore_flat_depth)
    if flat_dist > r - 0.05:
        flat_dist = r - 0.05
    if flat_dist < -r + 0.05:
        flat_dist = -r + 0.05

    bd = min(float(bore_depth), th - 0.5)
    if bd < 0.5:
        bd = float(bore_depth)

    if r > 0.1 and bd > 0.1:
        x_int_sq = r * r - flat_dist * flat_dist
        if x_int_sq < 0:
            x_int_sq = 0
        x_int = math.sqrt(x_int_sq)
        bore_wp = (
            cq.Workplane("XY")
            .moveTo(x_int, flat_dist)
            .threePointArc((0, -r), (-x_int, flat_dist))
            .lineTo(x_int, flat_dist)
            .close()
            .extrude(bd)
        )
        body = body.cut(bore_wp)

    return body

result = build({k: v[0] for k, v in PARAMS.items()})
