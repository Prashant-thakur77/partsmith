import cadquery as cq
import math

PARAMS = {
    "thickness": (15.0, 10.0, 20.0, 0.1, "mm", False, "Wheel thickness"),
    "outer_hole_dia": (12.71, 10.0, 15.0, 0.05, "mm", True, "Outer hole diameter"),
    "center_hole_dia": (7.183, 5.0, 10.0, 0.05, "mm", True, "Axle bore diameter"),
    "clearance": (0.2, 0.0, 0.6, 0.05, "mm", True, "Fit clearance (added to diameter)"),
    "outer_hole_count": (5, 3, 6, 1, "", True, "Number of outer holes"),
    "profile_scale": (1.0, 0.9, 1.1, 0.01, "", False, "Overall profile scale"),
}

# measured polyline points of wheel outer profile (mm) - centred near origin
BASE_POINTS = [
    [22.298,21.084],[17.843,24.959],[14.679,26.964],[12.2,28.159],[6.647,30.03],[0.508,30.845],[-3.336,30.737],[-6.202,30.347],[-11.568,28.875],[-16.266,26.553],[-18.331,25.137],[-21.469,22.448],[-23.422,20.383],[-25.587,17.537],[-28.202,12.792],[-29.998,7.559],[-30.626,4.258],[-30.859,1.576],[-30.528,-4.565],[-29.088,-10.284],[-26.615,-15.64],[-22.793,-20.777],[-18.355,-24.772],[-13.184,-27.87],[-9.934,-29.173],[-6.724,-30.077],[-0.71,-30.833],[5.369,-30.409],[9.648,-29.364],[12.302,-28.381],[17.146,-25.783],[19.356,-24.198],[22.208,-21.66],[25.737,-17.399],[27.19,-15.081],[28.751,-11.895],[30.415,-5.982],[30.866,0.146],[30.221,5.795],[28.509,11.477],[25.723,16.749]
]

# measured outer hole centres (5x) and centre bore
OUTER_HOLES_MEASURED = [
    [-17.576, 2.03],
    [-7.639, -16.039],
    [-3.458, 17.077],
    [12.622, -12.168],
    [15.205, 8.299],
]

CENTER_HOLE_MEASURED = [-0.171, -0.155]

def build(p: dict) -> cq.Workplane:
    thickness = float(p["thickness"])
    outer_dia = float(p["outer_hole_dia"]) + float(p["clearance"])
    center_dia = float(p["center_hole_dia"]) + float(p["clearance"])
    n_outer = int(round(float(p["outer_hole_count"])))
    scale = float(p["profile_scale"])

    # scale points
    pts = [[x * scale, y * scale] for x, y in BASE_POINTS]
    # also scale hole centres with profile scale to keep relative position
    outer_centres = [[x * scale, y * scale] for x, y in OUTER_HOLES_MEASURED]
    centre = [CENTER_HOLE_MEASURED[0] * scale, CENTER_HOLE_MEASURED[1] * scale]

    # clamp n_outer
    if n_outer < 0:
        n_outer = 0
    if n_outer > len(outer_centres):
        n_outer = len(outer_centres)

    wp = cq.Workplane("XY")
    # build polyline
    wp = wp.moveTo(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        wp = wp.lineTo(x, y)
    wp = wp.close()

    # extrude from Z=0 upward, centred at origin in XY, +Z up, mounting face Z=0
    base = wp.extrude(thickness, combine=True)

    # cut outer holes according to topology parameter
    # use exact measured positions for default count to match PartSpec
    if n_outer > 0:
        # if topology matches default (5) use measured centres directly
        # if reduced count, just use first n_outer measured positions
        use_centres = outer_centres[:n_outer]
        # for counts !=5 but user wants full circular pattern, generate circular pattern
        # we keep measured for determinism; alternative circular generation commented
        base = (
            base.faces(">Z")
            .workplane()
            .pushPoints(use_centres)
            .circle(outer_dia / 2.0)
            .cutThruAll()
        )

    # centre axle bore always present - through hole
    base = (
        base.faces(">Z")
        .workplane()
        .pushPoints([tuple(centre)])
        .circle(center_dia / 2.0)
        .cutThruAll()
    )

    return base

result = build({k: v[0] for k, v in PARAMS.items()})
