import cadquery as cq
import math

PARAMS = {
    "thickness": (1.5, 0.8, 3.0, 0.1, "mm", True, "Cover thickness"),
    "cover_length": (53.516, 50.0, 57.0, 0.1, "mm", True, "Overall length X"),
    "cover_width": (33.624, 30.0, 37.0, 0.1, "mm", True, "Overall width Y"),
    "tab_protrusion": (2.6, 1.5, 3.5, 0.1, "mm", True, "Hinge tab protrusion"),
    "hinge_tab_count": (3, 2, 5, 1, "", False, "Number of hinge tabs"),
}

def build(p: dict) -> cq.Workplane:
    thickness = float(p["thickness"])
    cover_length = float(p["cover_length"])
    cover_width = float(p["cover_width"])

    base_pts = [
        [-26.701, 13.991],
        [-26.749, 7.121],
        [-24.229, 6.971],
        [-24.053, 6.169],
        [-24.122, 3.613],
        [-26.714, 3.384],
        [-26.757, -3.483],
        [-24.137, -3.735],
        [-24.016, -6.747],
        [-24.263, -7.045],
        [-26.739, -7.203],
        [-26.738, -14.151],
        [-24.129, -14.325],
        [-24.005, -16.153],
        [-23.535, -16.727],
        [24.842, -16.811],
        [25.764, -16.504],
        [26.49, -15.631],
        [26.759, -13.757],
        [26.743, 14.513],
        [26.361, 15.702],
        [25.413, 16.544],
        [24.337, 16.813],
        [-23.013, 16.791],
        [-23.603, 16.623],
        [-23.942, 16.214],
        [-24.118, 14.166],
    ]

    xs = [pt[0] for pt in base_pts]
    ys = [pt[1] for pt in base_pts]
    base_len = max(xs) - min(xs)
    base_wid = max(ys) - min(ys)
    if base_len == 0:
        base_len = 1.0
    if base_wid == 0:
        base_wid = 1.0

    sx = cover_length / base_len
    sy = cover_width / base_wid

    pts = [(x * sx, y * sy) for x, y in base_pts]

    wp = cq.Workplane("XY")
    wp = wp.moveTo(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        wp = wp.lineTo(x, y)
    wp = wp.close()
    result = wp.extrude(thickness, both=False)
    return result

result = build({k: v[0] for k, v in PARAMS.items()})
