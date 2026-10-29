import cadquery as cq
import math

PARAMS = {
    "thickness": (7.5, 5.0, 10.0, 0.1, "mm", True, "Body thickness (Z extrusion from mounting face)"),
    "outline_scale": (1.0, 0.9, 1.1, 0.01, "", True, "Outline scale factor"),
    "hole_dia": (3.812, 3.0, 5.0, 0.05, "mm", True, "Mounting hole shaft diameter"),
    "hole_x": (7.369, 5.0, 10.0, 0.01, "mm", False, "Hole X position"),
    "hole_y": (-0.049, -2.0, 2.0, 0.01, "mm", False, "Hole Y position"),
    "csk_dia": (7.2, 5.5, 9.0, 0.1, "mm", True, "Countersink outer diameter (flat-head seat)"),
    "csk_angle": (90.0, 80.0, 100.0, 1.0, "deg", False, "Countersink included angle deg"),
    "hole_count": (1, 1, 2, 1, "", False, "Number of mounting holes"),
}

PROFILEPOINTS = [
    [-27.541, -0.123], [-27.1, -2.348], [-26.245, -4.101], [-24.598, -5.937],
    [-22.895, -7.022], [-21.417, -7.574], [-19.463, -7.793], [-10.122, -7.975],
    [20.993, -7.88], [23.435, -7.02], [25.651, -5.187], [26.878, -3.181],
    [27.541, -0.255], [27.47, 1.19], [26.842, 3.203], [25.515, 5.301],
    [24.502, 6.227], [22.12, 7.493], [20.114, 7.909], [-20.779, 7.89],
    [-23.702, 6.878], [-24.798, 6.168], [-25.898, 5.053], [-27.04, 3.103],
]

def build(p: dict) -> cq.Workplane:
    thickness = float(p["thickness"])
    scale = float(p["outline_scale"])
    hole_dia = float(p["hole_dia"])
    hole_x = float(p["hole_x"])
    hole_y = float(p["hole_y"])
    csk_dia = float(p["csk_dia"])
    csk_angle = float(p["csk_angle"])
    hole_count = int(round(float(p["hole_count"])))

    pts = [(x * scale, y * scale) for x, y in PROFILEPOINTS]

    body = cq.Workplane("XY").polyline(pts).close().extrude(thickness, combine=True)

    if hole_count >= 1:
        body = body.faces(">Z").workplane().pushPoints([(hole_x, hole_y)]).cskHole(hole_dia, csk_dia, csk_angle)

    if hole_count >= 2:
        body = body.faces(">Z").workplane().pushPoints([(-hole_x, -hole_y)]).cskHole(hole_dia, csk_dia, csk_angle)

    return body

result = build({k: v[0] for k, v in PARAMS.items()})
