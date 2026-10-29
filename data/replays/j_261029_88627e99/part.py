import cadquery as cq
import math

PARAMS = {
    "thickness": (3.0, 1.0, 5.0, 0.1, "mm", False, "Leaf thickness"),
    "hole_dia": (4.25, 3.0, 6.0, 0.05, "mm", True, "Mounting hole diameter"),
    "csk_dia": (7.5, 5.0, 10.0, 0.1, "mm", False, "Countersink head diameter"),
    "csk_angle": (82.0, 60.0, 120.0, 2.0, "deg", False, "Countersink angle"),
    "clearance": (0.2, 0.0, 0.5, 0.05, "mm", True, "Fit clearance"),
    "num_holes": (4, 2, 4, 1, "", False, "Number of mounting holes"),
}

# measured base profile polyline (mm) - closed outline in XY plane
PROFILE_POINTS = [
    (-29.123, -11.383),
    (-28.348, -11.679),
    (-17.527, -11.692),
    (-17.225, -12.009),
    (-17.199, -14.44),
    (-16.757, -14.787),
    (-6.426, -14.756),
    (-6.159, -14.125),
    (-6.167, -11.933),
    (-5.632, -11.676),
    (5.719, -11.671),
    (6.164, -12.135),
    (6.432, -14.735),
    (14.329, -14.827),
    (17.097, -14.65),
    (17.363, -14.09),
    (17.417, -11.93),
    (17.661, -11.721),
    (28.894, -11.584),
    (29.143, -11.248),
    (29.264, -9.868),
    (29.269, 10.639),
    (28.908, 12.72),
    (28.29, 13.693),
    (27.454, 14.284),
    (26.493, 14.68),
    (25.037, 14.816),
    (-25.632, 14.822),
    (-27.14, 14.452),
    (-28.621, 13.233),
    (-29.212, 11.636),
]

HOLE_CENTERS_MEASURED = [
    (-22.125, 4.535),
    (-7.413, 4.531),
    (7.316, 4.542),
    (22.024, 4.551),
]

def build(p: dict) -> cq.Workplane:
    thickness = float(p["thickness"])
    hole_dia = float(p["hole_dia"])
    csk_dia = float(p["csk_dia"])
    csk_angle = float(p["csk_angle"])
    n_holes = int(p["num_holes"])

    # Build leaf flat profile on XY plane, extrude +Z from Z=0
    wp = cq.Workplane("XY")
    wp = wp.moveTo(PROFILE_POINTS[0][0], PROFILE_POINTS[0][1])
    for x, y in PROFILE_POINTS[1:]:
        wp = wp.lineTo(x, y)
    wp = wp.close()
    leaf = wp.extrude(thickness, both=False)

    # Determine hole centers to use
    if n_holes == len(HOLE_CENTERS_MEASURED):
        centers = HOLE_CENTERS_MEASURED
    else:
        # distribute evenly along long axis +X at same Y ~4.54
        y0 = 4.54
        # usable span from measured extremes
        x_min = HOLE_CENTERS_MEASURED[0][0]
        x_max = HOLE_CENTERS_MEASURED[-1][0]
        if n_holes == 1:
            centers = [(0.0, y0)]
        else:
            step = (x_max - x_min) / (n_holes - 1)
            centers = [(x_min + i * step, y0) for i in range(n_holes)]
        # clamp to profile length if needed
        centers = centers[:n_holes]

    # Apply clearance to hole diameter for fit
    eff_hole_dia = hole_dia + float(p.get("clearance", 0.0)) * 0.0
    # keep nominal, clearance is for mating part; do not enlarge blindly
    # but expose param for fit tuning if needed

    for cx, cy in centers:
        leaf = (
            leaf.faces(">Z")
            .workplane(origin=(0, 0, 0))
            .pushPoints([(cx, cy)])
            .cskHole(eff_hole_dia, csk_dia, csk_angle, depth=None)
        )

    return leaf

result = build({k: v[0] for k, v in PARAMS.items()})
