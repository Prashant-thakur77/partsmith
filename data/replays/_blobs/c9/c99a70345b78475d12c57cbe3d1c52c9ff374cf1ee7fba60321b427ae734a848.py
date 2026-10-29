import cadquery as cq
import math

PARAMS = {
    "plate_t": (3.0, 1.5, 5.0, 0.1, "mm", False, "Plate thickness"),
    "hole_dia": (3.546, 2.5, 5.0, 0.05, "mm", True, "Mounting hole diameter"),
    "hole_x": (-16.83, -19.0, -14.0, 0.1, "mm", False, "Hole X"),
    "hole_y": (-1.005, -3.0, 3.0, 0.1, "mm", False, "Hole Y"),
    "clearance": (0.2, 0.05, 0.4, 0.05, "mm", True, "Fit clearance"),
    "hole_count": (1, 1, 2, 1, "", False, "Number of mounting holes"),
    "snap_x": (16.25, 13.0, 19.0, 0.1, "mm", False, "Snap center X"),
    "snap_y": (5.5, 5.5, 8.5, 0.1, "mm", False, "Snap center Y"),
    "snap_height": (10.5, 3.0, 12.0, 0.1, "mm", False, "Snap height above plate"),
    "snap_width": (3.2, 2.0, 12.0, 0.1, "mm", False, "Snap width along X"),
    "snap_thk": (1.1, 1.0, 3.0, 0.1, "mm", False, "Snap beam thickness Y"),
    "snap_overhang": (0.4, 0.3, 2.0, 0.1, "mm", True, "Hook overhang +Y"),
    "hook_h": (1.1, 0.8, 3.0, 0.1, "mm", False, "Hook vertical height"),
    "snap_chamfer": (0.4, 0.0, 1.0, 0.1, "mm", False, "Snap top chamfer"),
}

def build(p: dict) -> cq.Workplane:
    pts = [(-21.718, -7.995), (-20.968, -8.713), (-20.304, -8.995), (21.732, -8.916), (21.865, 6.755), (21.41, 7.009), (18.578, 7.007), (18.342, 8.87), (17.377, 9.049), (15.594, 8.941), (14.445, 8.426), (14.204, 7.22), (13.963, 7.025), (-20.498, 6.965), (-21.385, 6.451), (-21.884, 5.217), (-21.921, -7.124)]
    plate_t = float(p["plate_t"])
    hole_dia = float(p["hole_dia"]) + float(p["clearance"])
    hole_x = float(p["hole_x"])
    hole_y = float(p["hole_y"])
    hole_count = int(p["hole_count"])
    snap_x = float(p["snap_x"])
    snap_y = float(p["snap_y"])
    snap_height = float(p["snap_height"])
    snap_width = float(p["snap_width"])
    snap_thk = float(p["snap_thk"])
    snap_overhang = float(p["snap_overhang"])
    hook_h = float(p["hook_h"])

    # base plate centered at origin, mounting face on Z=0, long axis +X
    base = cq.Workplane("XY").polyline(pts).close().extrude(plate_t)

    # through holes - long axis X, centered pattern if count>1
    # single hole at measured location, second hole mirrored if topology count=2
    pts_holes = [(hole_x, hole_y)]
    if hole_count > 1:
        # second hole symmetric on X for generic clip family
        pts_holes.append((16.0, -1.005))
        pts_holes = pts_holes[:hole_count]
    base = base.faces(">Z").workplane().pushPoints(pts_holes).hole(hole_dia)

    # snap tower - replacement for broken snap
    # vertical flexible beam sitting on the small tab protrusion on +Y side
    # footprint is snap_width (X) by snap_thk (Y), height is snap_height above plate
    beam = (
        cq.Workplane("XY")
        .workplane(offset=plate_t)
        .moveTo(snap_x, snap_y)
        .rect(snap_width, snap_thk)
        .extrude(snap_height)
    )
    base = base.union(beam)

    # hook overhang - wedge on outer (+Y) face at top of beam, provides retention
    # triangular prism extruded along X (snap_width)
    # triangle in YZ plane: apex at outer top edge
    ty0 = snap_y + snap_thk * 0.5
    tz0 = plate_t + snap_height
    # triangle points (y,z): (ty0, tz0) tip, (ty0+overhang, tz0-hook_h/2) middle outer, (ty0, tz0-hook_h) root
    hook_pts = [
        (ty0, tz0),
        (ty0 + snap_overhang, tz0 - hook_h * 0.45),
        (ty0, tz0 - hook_h),
    ]
    # build hook as extrude along X
    hook = (
        cq.Workplane("YZ")
        .moveTo(hook_pts[0][0], hook_pts[0][1])
        .polyline(hook_pts[1:] + [hook_pts[0]])
        .close()
        .extrude(snap_width, both=False)
    )
    # extrude in YZ creates along X but centered; need to place correctly - cq extrude from YZ plane goes +X
    # shift so hook is centered on snap_x
    hook = hook.translate((-snap_width * 0.5, 0, 0))
    # the YZ workplane origin is (0,0,0), extrude translation already handled, but beam is at snap_x
    # translate hook to snap_x in X
    dx = snap_x
    hook = hook.translate((dx, 0, 0))

    base = base.union(hook)

    # small fillet/chamfer at top inner edge to ease mating and reduce stress, if requested
    # chamfer top edge of beam inner side by cutting
    try:
        if float(p["snap_chamfer"]) > 0.01:
            ch = float(p["snap_chamfer"])
            # inner top edge chamfer approximated as small cut
            cutter = (
                cq.Workplane("XY")
                .workplane(offset=plate_t + snap_height - ch)
                .moveTo(snap_x, snap_y - snap_thk * 0.5)
                .rect(snap_width + 0.2, ch * 2)
                .extrude(ch + 0.2)
            )
            # chamfer wedge: 45deg cut on inner side only - use intersection via cut with angled solid
            # simple approach: cut with a wedge prism on inner face
            wedge_pts = [
                (snap_y - snap_thk * 0.5, plate_t + snap_height),
                (snap_y - snap_thk * 0.5 + ch, plate_t + snap_height),
                (snap_y - snap_thk * 0.5, plate_t + snap_height - ch),
            ]
            wedge = (
                cq.Workplane("YZ")
                .moveTo(wedge_pts[0][0], wedge_pts[0][1])
                .polyline(wedge_pts[1:] + [wedge_pts[0]])
                .close()
                .extrude(snap_width + 1, both=False)
                .translate((- (snap_width + 1) * 0.5 + snap_x, 0, 0))
            )
            base = base.cut(wedge)
    except Exception:
        pass

    return base

result = build({k: v[0] for k, v in PARAMS.items()})
