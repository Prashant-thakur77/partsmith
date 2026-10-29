import cadquery as cq
import math

PARAMS = {
    "brick_length": (31.8, 28.0, 36.0, 0.1, "mm", True, "Brick length X"),
    "brick_width": (15.8, 12.0, 20.0, 0.1, "mm", True, "Brick width Y"),
    "brick_height": (9.6, 7.0, 12.0, 0.1, "mm", False, "Body height Z"),
    "stud_diameter": (4.8, 3.5, 6.0, 0.1, "mm", True, "Stud outer diameter"),
    "stud_height": (1.8, 1.0, 3.0, 0.1, "mm", False, "Stud height"),
    "stud_pitch": (8.0, 6.0, 10.0, 0.1, "mm", True, "Stud pitch"),
    "wall_thickness": (1.2, 0.8, 2.0, 0.1, "mm", True, "Wall thickness"),
    "clearance": (0.2, 0.0, 0.5, 0.05, "mm", True, "Fit clearance"),
    "studs_x": (4, 1, 8, 1, "", False, "Studs along X"),
    "studs_y": (2, 1, 4, 1, "", False, "Studs along Y"),
}

def build(p: dict) -> cq.Workplane:
    L = p["brick_length"]
    W = p["brick_width"]
    H = p["brick_height"]
    d = p["stud_diameter"]
    h = p["stud_height"]
    pitch = p["stud_pitch"]
    wt = p["wall_thickness"]
    nx = int(p["studs_x"])
    ny = int(p["studs_y"])

    # main body, mounting face on Z=0, centered in XY, long axis +X
    body = cq.Workplane("XY").box(L, W, H, centered=True).translate((0, 0, H / 2))

    # hollow underside (open at Z=0) - standard LEGO brick
    if wt > 0.01 and (L - 2 * wt) > 0.5 and (W - 2 * wt) > 0.5:
        inner_L = L - 2 * wt
        inner_W = W - 2 * wt
        inner_H = H - wt
        if inner_H > 0.2:
            cavity = cq.Workplane("XY").box(inner_L, inner_W, inner_H, centered=True).translate((0, 0, wt + inner_H / 2))
            body = body.cut(cavity)

    # studs on top face Z=H, 2x4 array at 8mm pitch
    # center pattern at origin
    if nx > 0 and ny > 0 and d > 0.1 and h > 0.01:
        x0 = - (nx - 1) * pitch / 2.0
        y0 = - (ny - 1) * pitch / 2.0
        for ix in range(nx):
            x = x0 + ix * pitch
            for iy in range(ny):
                y = y0 + iy * pitch
                stud = cq.Workplane("XY").workplane(offset=H).moveTo(x, y).circle(d / 2).extrude(h)
                body = body.union(stud)

    return body

result = build({k: v[0] for k, v in PARAMS.items()})
