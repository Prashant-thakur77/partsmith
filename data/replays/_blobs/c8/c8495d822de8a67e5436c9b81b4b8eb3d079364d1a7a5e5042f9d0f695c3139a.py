import cadquery as cq
import math

PARAMS = {
    "thickness": (2.5, 1.0, 4.0, 0.1, "mm", True, "Base plate thickness"),
    "hole_dia": (3.433, 2.5, 4.5, 0.05, "mm", True, "Mounting hole diameter"),
    "hole_spacing": (25.313, 20.0, 30.0, 0.1, "mm", False, "Hole centre spacing X"),
    "rib_width": (0.9, 0.6, 1.6, 0.1, "mm", False, "Tooth/rib width along X"),
    "rib_height": (1.45, 0.8, 3.0, 0.05, "mm", True, "Tooth/rib height above plate"),
    "rib_pitch": (2.1, 1.2, 3.5, 0.05, "mm", False, "Rib pitch along X"),
    "rib_length": (11.8, 8.0, 13.0, 0.1, "mm", False, "Rib length along Y"),
    "rib_count": (7, 3, 13, 1, "", False, "Number of transverse ribs"),
    "clearance": (0.2, 0.0, 0.5, 0.05, "mm", True, "Print clearance"),
}

# measured outer polyline centred at origin, long axis +X
BASE_POINTS = [
    [-17.159, 4.493],
    [-17.193, -4.372],
    [-16.772, -5.365],
    [-16.044, -5.831],
    [15.432, -5.934],
    [16.567, -5.535],
    [17.171, -4.617],
    [17.171, 3.955],
    [16.959, 4.93],
    [16.048, 5.637],
    [8.469, 5.705],
    [7.526, 5.946],
    [5.629, 5.694],
    [4.409, 5.941],
    [2.858, 5.664],
    [1.918, 5.953],
    [0.173, 5.752],
    [-1.462, 5.941],
    [-2.517, 5.732],
    [-6.556, 5.919],
    [-8.16, 5.673],
    [-15.691, 5.69],
    [-16.662, 5.287],
]

def build(p: dict) -> cq.Workplane:
    thickness = float(p["thickness"])
    hole_dia = float(p["hole_dia"])
    hole_spacing = float(p["hole_spacing"])
    rib_width = float(p["rib_width"])
    rib_height = float(p["rib_height"])
    rib_pitch = float(p["rib_pitch"])
    rib_length = float(p["rib_length"])
    rib_count = int(round(float(p["rib_count"])))

    # base plate extruded from Z=0 upward, centred at origin, +Z up, long axis +X
    pts = BASE_POINTS
    w = cq.Workplane("XY").moveTo(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        w = w.lineTo(x, y)
    w = w.close().extrude(thickness, both=False)

    # two mounting through-holes symmetric about origin along X
    # measured centers were (-12.652, -0.098) and (12.661, -0.1) => spacing ~25.313
    hx = hole_spacing / 2.0
    hole_r = hole_dia / 2.0
    for cx, cy in [(-hx, -0.099), (hx, -0.099)]:
        cutter = cq.Workplane("XY").moveTo(cx, cy).circle(hole_r).extrude(thickness + 0.4, both=False)
        # ensure cutter spans Z range with small margin
        cutter = cutter.translate((0, 0, -0.2))
        w = w.cut(cutter)

    # transverse toothed strap ribs on top face
    # distributed centred at 0, pitch 2.1, covering rib_count positions
    if rib_count > 0 and rib_height > 0.01:
        # compute start so array is centred at origin
        total_span = (rib_count - 1) * rib_pitch
        start_x = -total_span / 2.0
        for i in range(rib_count):
            cx = start_x + i * rib_pitch
            rib = cq.Workplane("XY").workplane(offset=thickness).moveTo(cx, 0).rect(rib_width, rib_length, centered=True).extrude(rib_height, both=False)
            w = w.union(rib)

    return w

result = build({k: v[0] for k, v in PARAMS.items()})
