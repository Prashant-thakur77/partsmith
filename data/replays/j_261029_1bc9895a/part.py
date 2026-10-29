import cadquery as cq
import math

PARAMS = {
    "card_length": (31.94, 28.0, 35.0, 0.1, "mm", True, "Length X"),
    "card_width": (24.0, 20.0, 28.0, 0.1, "mm", True, "Width Y"),
    "thickness": (2.1, 1.0, 4.0, 0.1, "mm", True, "Thickness Z"),
    "chamfer_size": (4.0, 2.0, 6.0, 0.1, "mm", False, "Corner chamfer"),
    "contact_count": (9, 0, 9, 1, "", False, "Contact pads count"),
}

BASE_PTS = [
    [-15.949, 11.765],
    [-15.902, -11.804],
    [-14.649, -12.034],
    [15.689, -12.001],
    [15.991, -11.76],
    [15.95, 7.857],
    [11.959, 11.974],
    [-15.486, 12.009],
]

def build(p: dict) -> cq.Workplane:
    card_length = float(p.get("card_length", 31.94))
    card_width = float(p.get("card_width", 24.0))
    thickness = float(p.get("thickness", 2.1))
    chamfer_size = float(p.get("chamfer_size", 4.0))
    contact_count = int(p.get("contact_count", 9))

    xs0 = [pt[0] for pt in BASE_PTS]
    ys0 = [pt[1] for pt in BASE_PTS]
    min_x0 = min(xs0)
    max_x0 = max(xs0)
    min_y0 = min(ys0)
    max_y0 = max(ys0)
    meas_len = max_x0 - min_x0
    meas_wid = max_y0 - min_y0
    cx0 = sum(xs0) / len(xs0)
    cy0 = sum(ys0) / len(ys0)

    sx = card_length / meas_len if meas_len != 0 else 1.0
    sy = card_width / meas_wid if meas_wid != 0 else 1.0

    scaled = []
    for x, y in BASE_PTS:
        nx = (x - cx0) * sx
        ny = (y - cy0) * sy
        scaled.append((nx, ny))

    corner_x = card_length / 2.0
    corner_y = card_width / 2.0

    if len(scaled) >= 8:
        scaled[5] = (corner_x, corner_y - chamfer_size)
        scaled[6] = (corner_x - chamfer_size, corner_y)
        scaled[0] = (-corner_x, corner_y)
        scaled[1] = (-corner_x, -corner_y)
        scaled[2] = (-corner_x + 1.2 * sx, -corner_y)
        scaled[3] = (corner_x, -corner_y)
        scaled[4] = (corner_x, -corner_y + 0.3 * sy)
        scaled[7] = (-corner_x, corner_y)

    xs = [pt[0] for pt in scaled]
    ys = [pt[1] for pt in scaled]
    cx = (max(xs) + min(xs)) / 2.0
    cy = (max(ys) + min(ys)) / 2.0
    centered = [(x - cx, y - cy) for x, y in scaled]

    base = cq.Workplane("XY").polyline(centered).close().extrude(thickness)

    if contact_count > 0:
        pad_w = 2.0
        pad_d = 3.0
        pad_h = 0.15
        gap = 0.6
        total_w = contact_count * pad_w + (contact_count - 1) * gap
        start_x = -total_w / 2.0 + pad_w / 2.0
        y_pos = -card_width / 2.0 + pad_d / 2.0 + 1.0
        for i in range(contact_count):
            x_pos = start_x + i * (pad_w + gap)
            pad = (
                cq.Workplane("XY")
                .workplane(offset=thickness)
                .center(x_pos, y_pos)
                .rect(pad_w, pad_d)
                .extrude(pad_h)
            )
            base = base.union(pad)

    return base

result = build({k: v[0] for k, v in PARAMS.items()})
