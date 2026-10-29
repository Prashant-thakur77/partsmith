import cadquery as cq
import math

PARAMS = {
    "thickness": (7.5, 5.0, 10.0, 0.1, "mm", False, "Plate thickness"),
    "hole_dia": (3.4, 2.5, 5.5, 0.05, "mm", True, "Mounting hole diameter"),
    "hole_x": (7.369, 0.0, 15.0, 0.1, "mm", False, "Hole X offset from origin"),
    "hole_y": (-0.049, -3.0, 3.0, 0.05, "mm", False, "Hole Y offset from origin"),
    "csink_head_dia": (7.0, 5.0, 10.0, 0.1, "mm", False, "Countersink head diameter"),
    "csink_depth": (2.0, 0.8, 3.5, 0.1, "mm", False, "Countersink depth"),
    "csink_angle": (90.0, 60.0, 120.0, 5.0, "deg", False, "Countersink angle"),
    "clearance": (0.2, 0.0, 0.5, 0.05, "mm", True, "FDM fit clearance"),
    "length_scale": (1.0, 0.9, 1.1, 0.01, "", False, "Length scale factor"),
    "width_scale": (0.9, 0.9, 1.1, 0.01, "", False, "Width scale factor"),
    "hole_count": (1, 1, 1, 1, "", False, "Number of mounting holes"),
}

def build(p: dict) -> cq.Workplane:
    base_pts_raw = [
        [-27.541, -0.123],
        [-27.1, -2.348],
        [-26.245, -4.101],
        [-24.598, -5.937],
        [-22.895, -7.022],
        [-21.417, -7.574],
        [-19.463, -7.793],
        [-10.122, -7.975],
        [20.993, -7.88],
        [23.435, -7.02],
        [25.651, -5.187],
        [26.878, -3.181],
        [27.541, -0.255],
        [27.47, 1.19],
        [26.842, 3.203],
        [25.515, 5.301],
        [24.502, 6.227],
        [22.12, 7.493],
        [20.114, 7.909],
        [-20.779, 7.89],
        [-23.702, 6.878],
        [-24.798, 6.168],
        [-25.898, 5.053],
        [-27.04, 3.103],
    ]

    lx = p["length_scale"]
    wx = p["width_scale"]
    pts = [[x * lx, y * wx] for x, y in base_pts_raw]

    thickness = p["thickness"]
    clearance = p["clearance"]
    hole_dia_eff = p["hole_dia"] + clearance
    cs_dia_eff = p["csink_head_dia"] + clearance
    cs_angle = p["csink_angle"]
    hole_x = p["hole_x"]
    hole_y = p["hole_y"]
    hole_n = int(p["hole_count"])

    wp = cq.Workplane("XY")
    wp = wp.moveTo(pts[0][0], pts[0][1])
    wp = wp.spline(pts[1:], periodic=True)
    wp = wp.close()
    body = wp.extrude(thickness, both=False)

    if hole_n >= 1:
        body = (
            body.faces(">Z")
            .workplane()
            .moveTo(hole_x, hole_y)
            .cskHole(hole_dia_eff, cs_dia_eff, cs_angle, depth=None)
        )

    if hole_n >= 2:
        body = (
            body.faces(">Z")
            .workplane()
            .moveTo(-hole_x, hole_y)
            .cskHole(hole_dia_eff, cs_dia_eff, cs_angle, depth=None)
        )

    return body

result = build({k: v[0] for k, v in PARAMS.items()})
