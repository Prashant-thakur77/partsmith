import cadquery as cq
import math

PARAMS = {
    "length": (31.8, 30.0, 33.0, 0.1, "mm", True, "Body length X"),
    "width": (15.8, 14.0, 17.0, 0.1, "mm", True, "Body width Y"),
    "thickness": (9.6, 8.0, 11.0, 0.1, "mm", True, "Body thickness Z"),
    "stud_dia": (4.8, 4.0, 5.5, 0.1, "mm", True, "Stud outer diameter"),
    "stud_height": (1.8, 1.0, 2.5, 0.1, "mm", True, "Stud height above body"),
    "stud_pitch": (7.9, 7.0, 9.0, 0.1, "mm", True, "Stud pitch"),
    "stud_cols": (4, 2, 6, 1, "", False, "Studs along X (count)"),
    "stud_rows": (2, 1, 3, 1, "", False, "Studs along Y (count)"),
}

def build(p: dict) -> cq.Workplane:
    length = float(p["length"])
    width = float(p["width"])
    thickness = float(p["thickness"])
    stud_dia = float(p["stud_dia"])
    stud_height = float(p["stud_height"])
    stud_pitch = float(p["stud_pitch"])
    cols = int(round(float(p["stud_cols"])))
    rows = int(round(float(p["stud_rows"])))

    # Base body - solid to thickness, mounting face on Z=0, centred at origin, long axis X
    # Measured base_profile points_mm approx 31.8 x 15.8 rect; using rect for robustness
    body = cq.Workplane("XY").rect(length, width).extrude(thickness)

    # Stud grid centred on body
    # For 2x4: cols=4 -> x = -12, -4, 4, 12 ; rows=2 -> y = -4, 4 when pitch=8
    if cols < 1:
        cols = 1
    if rows < 1:
        rows = 1

    x0 = -((cols - 1) * stud_pitch) / 2.0
    y0 = -((rows - 1) * stud_pitch) / 2.0

    r = stud_dia / 2.0

    for ix in range(cols):
        x = x0 + ix * stud_pitch
        for iy in range(rows):
            y = y0 + iy * stud_pitch
            stud = (
                cq.Workplane("XY")
                .workplane(offset=thickness)
                .moveTo(x, y)
                .circle(r)
                .extrude(stud_height)
            )
            body = body.union(stud)

    return body

result = build({k: v[0] for k, v in PARAMS.items()})
