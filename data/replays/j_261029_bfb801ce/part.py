import cadquery as cq
import math

# Reconstructed outline: base_profile with broken central notch at -X filled to straight edge.
# Notch points 4..13 removed, left edge closed between points 3 and 14.
RECONSTRUCTED_OUTLINE = [
    (-25.987, 13.34),
    (-26.314, 11.99),
    (-26.268, 3.962),
    (-26.154, -10.251),
    (-26.31, -12.042),
    (-25.997, -13.272),
    (-25.431, -14.116),
    (-24.601, -14.763),
    (-22.905, -15.18),
    (23.009, -15.154),
    (23.785, -14.597),
    (23.953, -3.022),
    (24.252, -2.627),
    (25.913, -2.56),
    (26.266, -2.351),
    (26.227, 2.625),
    (24.617, 2.671),
    (23.956, 3.063),
    (23.924, 13.843),
    (23.806, 14.531),
    (23.443, 14.991),
    (22.47, 15.194),
    (-23.191, 15.163),
    (-24.868, 14.636),
]

PARAMS = {
    "cover_length": (53.0, 50.0, 55.0, 0.1, "mm", True, "Overall length X"),
    "cover_width": (30.6, 28.0, 32.0, 0.1, "mm", True, "Overall width Y"),
    "thickness": (2.0, 1.0, 3.0, 0.1, "mm", False, "Plate thickness Z"),
    "clearance": (0.0, 0.0, 0.5, 0.05, "mm", True, "Fit clearance XY"),
    "corner_radius": (1.2, 0.5, 2.5, 0.1, "mm", False, "Corner rounding radius"),
    "latch_protrusion": (2.35, 1.5, 3.0, 0.1, "mm", True, "Right side latch protrusion"),
    "latch_width": (5.2, 4.0, 7.0, 0.1, "mm", True, "Latch tab width Y"),
    "rib_count": (0, 0, 3, 1, "", False, "Underside ribs count"),
    "rib_height": (0.8, 0.0, 1.5, 0.1, "mm", False, "Underside rib height"),
}

def build(p: dict) -> cq.Workplane:
    # Base outline is already centred near origin with long axis +X, mounting face on Z=0
    # Apply clearance as uniform inset for FDM PLA fit via scaling
    cl = float(p["clearance"])
    th = float(p["thickness"])
    cr = float(p["corner_radius"])

    # clearance inset: scale points slightly inward by clearance
    # compute scale factors from nominal extents
    xs = [pt[0] for pt in RECONSTRUCTED_OUTLINE]
    ys = [pt[1] for pt in RECONSTRUCTED_OUTLINE]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    nom_len = x_max - x_min
    nom_wid = y_max - y_min

    # target dimensions minus clearance
    tgt_len = float(p["cover_length"]) - cl
    tgt_wid = float(p["cover_width"]) - cl
    sx = tgt_len / nom_len if nom_len != 0 else 1.0
    sy = tgt_wid / nom_wid if nom_wid != 0 else 1.0

    pts = [(x * sx, y * sy) for x, y in RECONSTRUCTED_OUTLINE]

    # main plate, Z from 0 to thickness, centred in XY
    plate = (
        cq.Workplane("XY")
        .polyline(pts)
        .close()
        .extrude(th, both=False)
    )

    # move to have mounting face on Z=0 and keep centred at origin (already)
    # polyline was centred, extrude creates bottom at 0, top at +th => correct

    # soft edge break for printability and feel, limited to vertical edges
    try:
        plate = plate.edges("|Z").fillet(min(cr, 0.9))
    except Exception:
        pass

    # optional underside ribs (unknowns: rib height) - centred, running along X
    rc = int(p["rib_count"])
    rh = float(p["rib_height"])
    if rc > 0 and rh > 0.05:
        # ribs inset 3mm from left/right ends, 1.2mm wide
        rib_w = 1.2
        rib_len = tgt_len - 6.0
        y_span = tgt_wid - 4.0
        if rc == 1:
            y_positions = [0.0]
        else:
            step = y_span / (rc - 1) if rc > 1 else 0
            y0 = -y_span / 2.0
            y_positions = [y0 + i * step for i in range(rc)]
        for ypos in y_positions:
            rib = (
                cq.Workplane("XY")
                .workplane(offset=0)
                .moveTo(-rib_len / 2.0, ypos - rib_w / 2.0)
                .rect(rib_len, rib_w)
                .extrude(rh)
            )
            # ribs are on underside? spec says mounting face on Z=0, +Z up.
            # Interpret ribs as underside features protruding -Z, but keep on +Z for printing
            # as small top stiffeners to avoid interfering with mounting face.
            # Place on top face instead to keep mounting face flat.
            rib = rib.translate((0, 0, th - 0.01))
            plate = plate.union(rib)

    return plate

result = build({k: v[0] for k, v in PARAMS.items()})
