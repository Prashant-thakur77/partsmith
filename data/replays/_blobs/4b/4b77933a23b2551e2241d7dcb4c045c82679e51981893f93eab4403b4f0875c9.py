import cadquery as cq
import math

PARAMS = {
    "thickness": (1.5, 0.8, 3.0, 0.1, "mm", False, "Cover thickness"),
    "clearance": (0.2, 0.0, 0.5, 0.05, "mm", True, "XY fit clearance"),
    "latch_height": (3.2, 1.0, 6.0, 0.1, "mm", True, "Latch height off inside face"),
    "latch_width": (12.0, 6.0, 20.0, 0.5, "mm", True, "Latch width along Y"),
    "latch_thickness": (1.4, 0.8, 2.2, 0.1, "mm", True, "Latch wall thickness"),
    "latch_pos_y": (0.0, -5.0, 5.0, 0.5, "mm", False, "Latch Y offset from center"),
    "latch_count": (1, 1, 2, 1, "", False, "Number of snap latches"),
    "fillet_r": (0.6, 0.0, 1.5, 0.1, "mm", False, "Edge fillet radius"),
    "wall_height": (0.0, 0.0, 2.0, 0.1, "mm", True, "Optional perimeter lip height"),
}

def build(p: dict) -> cq.Workplane:
    pts = [(-26.701,13.991),(-26.749,7.121),(-24.229,6.971),(-24.053,6.169),(-24.122,3.613),(-26.714,3.384),(-26.757,-3.483),(-24.137,-3.735),(-24.016,-6.747),(-24.263,-7.045),(-26.739,-7.203),(-26.738,-14.151),(-24.129,-14.325),(-24.005,-16.153),(-23.535,-16.727),(24.842,-16.811),(25.764,-16.504),(26.49,-15.631),(26.759,-13.757),(26.743,14.513),(26.361,15.702),(25.413,16.544),(24.337,16.813),(-23.013,16.791),(-23.603,16.623),(-23.942,16.214),(-24.118,14.166)]

    # base plate on XY, mounting face at Z=0, thickness +Z
    base = cq.Workplane("XY").polyline(pts).close().extrude(p["thickness"])

    # optional perimeter lip on inside face (mounting face) to help seating
    wh = p["wall_height"]
    if wh > 0.01:
        # thin wall inset 1.2mm from edge
        wall_w = 1.0
        base = base.faces("<Z").workplane().polyline(pts).close().offset2D(-wall_w).extrude(-wh)

    # snap latch(es) at right edge (+X side) standing off inside face (-Z)
    lh = p["latch_height"]
    lw = p["latch_width"]
    lt = p["latch_thickness"]
    if lh > 0.01 and lt > 0.01:
        # X position of right edge, slightly inset so latch sits on cover
        latch_x = 25.2
        # latch_count topology parameter - 1 or 2 latches distributed in Y
        n = int(p["latch_count"])
        if n == 1:
            ys = [p["latch_pos_y"]]
        else:
            ys = [-5.0, 5.0]
        for y0 in ys:
            # vertical wall down from mounting face
            base = base.faces("<Z").workplane().center(latch_x, y0).rect(lt, lw).extrude(-lh)
            # hook tip outward in +X at bottom of latch
            tip_h = 1.0
            tip_out = 0.9
            # create tip as separate solid and union
            tip = cq.Workplane("XY").workplane(offset=-lh).center(latch_x + lt/2.0 + tip_out/2.0 - 0.2, y0).rect(tip_out, lw).extrude(tip_h)
            base = base.union(tip)

    # soft fillet on top edges if requested
    fr = p["fillet_r"]
    if fr > 0.01:
        try:
            base = base.edges("|Z").fillet(fr)
        except Exception:
            pass

    return base

result = build({k: v[0] for k, v in PARAMS.items()})
