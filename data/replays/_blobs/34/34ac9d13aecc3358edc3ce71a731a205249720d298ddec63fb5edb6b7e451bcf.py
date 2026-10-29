import cadquery as cq
import math

PARAMS = {
    "thickness": (15.0, 10.0, 20.0, 0.1, "mm", False, "Wheel thickness (Z extrusion)"),
    "center_hole_dia": (7.183, 6.0, 9.0, 0.01, "mm", True, "Center axle bore diameter"),
    "outer_hole_dia": (12.7, 11.0, 14.0, 0.01, "mm", False, "Outer lightening hole diameter"),
    "num_outer_holes": (5, 0, 5, 1, "", False, "Number of outer lightening holes"),
    "fit_clearance": (0.2, 0.0, 0.5, 0.05, "mm", True, "Fit clearance (added to holes)"),
}

def build(p: dict) -> cq.Workplane:
    thickness = float(p["thickness"])
    center_hole_dia = float(p["center_hole_dia"])
    outer_hole_dia = float(p["outer_hole_dia"])
    num_outer_holes = int(p["num_outer_holes"])
    fit_clearance = float(p["fit_clearance"])

    # Measured base profile polyline (caster wheel outline) - XY plane
    pts = [
        [22.298,21.084],[17.843,24.959],[14.679,26.964],[12.2,28.159],[6.647,30.03],[0.508,30.845],[-3.336,30.737],[-6.202,30.347],[-11.568,28.875],[-16.266,26.553],[-18.331,25.137],[-21.469,22.448],[-23.422,20.383],[-25.587,17.537],[-28.202,12.792],[-29.998,7.559],[-30.626,4.258],[-30.859,1.576],[-30.528,-4.565],[-29.088,-10.284],[-26.615,-15.64],[-22.793,-20.777],[-18.355,-24.772],[-13.184,-27.87],[-9.934,-29.173],[-6.724,-30.077],[-0.71,-30.833],[5.369,-30.409],[9.648,-29.364],[12.302,-28.381],[17.146,-25.783],[19.356,-24.198],[22.208,-21.66],[25.737,-17.399],[27.19,-15.081],[28.751,-11.895],[30.415,-5.982],[30.866,0.146],[30.221,5.795],[28.509,11.477],[25.723,16.749]
    ]

    # Effective diameters with clearance where fit matters
    center_d_eff = center_hole_dia + fit_clearance
    outer_d_eff = outer_hole_dia + fit_clearance

    # Outer lightening hole centers from PartSpec (5 holes)
    outer_centers_all = [
        [-17.576, 2.03],
        [-7.639, -16.039],
        [-3.458, 17.077],
        [12.622, -12.168],
        [15.205, 8.299],
    ]
    # Topology parameter controls how many outer holes are cut
    outer_centers = outer_centers_all[:max(0, min(num_outer_holes, len(outer_centers_all)))]

    # Center hole
    center_center = [-0.171, -0.155]

    # Build solid wheel body extruded from Z=0 up (mounting face on Z=0, centred in XY)
    w = cq.Workplane("XY")
    w = w.moveTo(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        w = w.lineTo(x, y)
    w = w.close().extrude(thickness, combine=True)

    # Cut center axle hole (through hole, vertical cylinder)
    w = w.faces(">Z").workplane().pushPoints([tuple(center_center)]).circle(center_d_eff/2.0).cutThruAll()

    # Cut outer lightening holes
    if outer_centers:
        w = w.faces(">Z").workplane().pushPoints([tuple(c) for c in outer_centers]).circle(outer_d_eff/2.0).cutThruAll()

    return w

result = build({k: v[0] for k, v in PARAMS.items()})
