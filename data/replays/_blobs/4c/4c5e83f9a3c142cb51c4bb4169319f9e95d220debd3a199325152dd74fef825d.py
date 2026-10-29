import cadquery as cq
import math

PARAMS = {
    "thickness": (16.0, 10.0, 22.0, 0.5, "mm", False, "Knob thickness"),
    "bore_dia": (6.0, 4.0, 8.0, 0.1, "mm", True, "D-shaft diameter"),
    "bore_flat": (1.0, 0.5, 2.0, 0.1, "mm", True, "Flat depth from OD"),
    "bore_depth": (12.0, 6.0, 16.0, 0.5, "mm", True, "Bore depth (blind from Z=0)"),
    "clearance": (0.2, 0.0, 0.5, 0.05, "mm", True, "Diametric fit clearance"),
    "chamfer": (0.5, 0.0, 1.5, 0.1, "mm", False, "Top edge chamfer"),
    "knurl_count": (24, 0, 48, 1, "", False, "Number of knurls (0=none)"),
    "knurl_depth": (0.6, 0.2, 1.2, 0.1, "mm", False, "Knurl groove depth"),
}

def build(p: dict) -> cq.Workplane:
    thickness = float(p["thickness"])
    bore_dia = float(p["bore_dia"])
    bore_flat = float(p["bore_flat"])
    bore_depth = float(p["bore_depth"])
    clearance = float(p["clearance"])
    chamfer = float(p["chamfer"])
    knurl_count = int(p["knurl_count"])
    knurl_depth = float(p["knurl_depth"])

    # measured base profile polyline - XY plane
    pts = [
        [11.16,10.013],[7.746,12.305],[6.378,13.574],[1.725,14.836],[-3.468,14.824],[-7.94,13.136],[-9.07,12.109],[-9.641,11.881],[-11.519,10.024],[-12.389,8.419],[-13.385,7.362],[-14.221,5.725],[-14.647,3.68],[-14.893,-0.475],[-14.684,-2.985],[-14.081,-5.229],[-12.644,-8.3],[-8.337,-12.611],[-4.742,-14.213],[-1.327,-14.825],[1.322,-14.833],[4.245,-14.401],[6.401,-13.803],[9.478,-11.953],[12.437,-8.948],[13.143,-7.809],[14.215,-5.09],[14.662,-3.271],[14.887,1.123],[14.322,2.909],[14.246,4.05],[13.436,6.493],[12.576,7.456]
    ]

    # main body extruded from Z=0 upward (+Z up, mounting face on Z=0)
    wp = cq.Workplane("XY")
    wp = wp.moveTo(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        wp = wp.lineTo(x, y)
    wp = wp.close()
    solid = wp.extrude(thickness)

    # top edge chamfer if requested
    if chamfer > 1e-6:
        try:
            solid = solid.edges(">Z").chamfer(chamfer)
        except Exception:
            pass

    # D-shaft bore: diameter includes clearance, flat stays as defined
    # effective circle radius
    eff_dia = bore_dia + clearance  # diametric clearance
    r = eff_dia / 2.0
    # flat line distance from centre: r - flat_depth
    # flat is at +Y side, bore centred at origin, long axis +X
    flat_y = r - bore_flat
    # clamp to avoid sqrt negative
    if flat_y > r:
        flat_y = r - 0.1
    if flat_y < -r:
        flat_y = -r + 0.1
    x0_sq = r * r - flat_y * flat_y
    if x0_sq < 0:
        x0_sq = 0
    x0 = math.sqrt(x0_sq)

    # limit bore depth to not exceed thickness
    bd = min(bore_depth, thickness - 0.2)
    if bd < 0.5:
        bd = thickness * 0.75

    # D profile: line across flat + large arc around bottom
    # A (-x0, flat_y) -> B (x0, flat_y) -> arc via (0,-r) -> A
    if x0 < 1e-6:
        # fallback to full circle
        cutter2d = cq.Workplane("XY").circle(r)
        bore_cutter = cutter2d.extrude(bd)
    else:
        bore_cutter = (
            cq.Workplane("XY")
            .moveTo(-x0, flat_y)
            .lineTo(x0, flat_y)
            .threePointArc((0, -r), (-x0, flat_y))
            .close()
            .extrude(bd)
        )
    solid = solid.cut(bore_cutter)

    # optional knurls / grip grooves around perimeter
    # radial grooves cut through thickness
    if knurl_count > 0 and knurl_depth > 1e-6:
        # approximate outer radius from profile max distance
        max_r = 0.0
        for x, y in pts:
            d = math.hypot(x, y)
            if d > max_r:
                max_r = d
        # create a single groove cutter at angle 0, then rotate
        # groove is a small rectangular prism cutting inward from outer radius
        # size along radial ~ knurl_depth*2, tangential ~ 1.2mm
        groove_w = max(0.8, (2 * math.pi * max_r / max(knurl_count, 1)) * 0.35)
        groove_h = thickness + 0.4
        # base cutter positioned at outer radius
        # use box centred at (max_r, 0)
        for i in range(knurl_count):
            ang = 360.0 / knurl_count * i
            cutter = (
                cq.Workplane("XY")
                .workplane(offset=0)
                .moveTo(max_r - knurl_depth * 0.3, 0)
                .rect(knurl_depth * 1.8, groove_w)
                .extrude(groove_h)
            )
            cutter = cutter.rotate((0, 0, 0), (0, 0, 1), ang)
            # translate slightly in Z to ensure clean cut (cover 0..thickness)
            cutter = cutter.translate((0, 0, -0.1))
            solid = solid.cut(cutter)

    return solid

result = build({k: v[0] for k, v in PARAMS.items()})
