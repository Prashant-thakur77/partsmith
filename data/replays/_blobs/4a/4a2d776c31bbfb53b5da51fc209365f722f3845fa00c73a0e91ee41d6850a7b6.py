import cadquery as cq
import math

PARAMS = {
    "card_length": (85.6, 80.0, 90.0, 0.1, "mm", False, "Length X"),
    "card_width": (53.98, 50.0, 60.0, 0.1, "mm", False, "Width Y"),
    "thickness": (0.85, 0.4, 2.0, 0.05, "mm", False, "Thickness Z"),
    "corner_radius": (3.18, 1.0, 5.0, 0.1, "mm", False, "Corner radius"),
    "edge_bevel": (0.15, 0.0, 0.4, 0.05, "mm", False, "Edge bevel"),
    "clearance": (0.2, 0.05, 0.5, 0.05, "mm", True, "Fit clearance"),
    "stack_count": (1, 1, 5, 1, "", False, "Stack count"),
    "stack_gap": (1.0, 0.5, 5.0, 0.1, "mm", False, "Stack gap"),
}

MEASURED_POINTS = [[-42.337,-25.492],[-41.586,-26.328],[-40.64,-26.857],[-38.659,-27.033],[39.973,-26.996],[41.343,-26.518],[42.442,-25.288],[42.838,-23.434],[42.763,24.378],[42.403,25.417],[41.118,26.646],[39.497,27.022],[-39.429,27.016],[-41.291,26.507],[-42.383,25.409],[-42.76,24.431],[-42.831,-22.706],[-42.793,-24.211]]

def build(p: dict) -> cq.Workplane:
    L = float(p["card_length"])
    W = float(p["card_width"])
    T = float(p["thickness"])
    R = float(p["corner_radius"])
    bevel = float(p["edge_bevel"])
    n = int(p["stack_count"])
    gap = float(p["stack_gap"])

    R = min(R, min(L, W) / 2.0 - 0.1)
    if R < 0.1:
        R = 0.1

    base = None
    try:
        base = cq.Workplane("XY").rect(L, W, centered=True, rx=R).extrude(T)
    except Exception:
        xs = [pt[0] for pt in MEASURED_POINTS]
        ys = [pt[1] for pt in MEASURED_POINTS]
        orig_L = max(xs) - min(xs)
        orig_W = max(ys) - min(ys)
        if orig_L < 1e-6:
            orig_L = L
        if orig_W < 1e-6:
            orig_W = W
        sx = L / orig_L
        sy = W / orig_W
        cx = (max(xs) + min(xs)) * 0.5
        cy = (max(ys) + min(ys)) * 0.5
        scaled = [((x - cx) * sx, (y - cy) * sy) for x, y in MEASURED_POINTS]
        wp = cq.Workplane("XY")
        wp = wp.moveTo(scaled[0][0], scaled[0][1])
        for x, y in scaled[1:]:
            wp = wp.lineTo(x, y)
        wp = wp.close().extrude(T)
        base = wp

    if bevel > 0.01 and T > bevel * 2:
        try:
            base = base.edges(">Z").chamfer(bevel * 0.6)
        except Exception:
            pass

    if n > 1:
        result = None
        for i in range(n):
            zoff = i * (T + gap)
            card = base.translate((0, 0, zoff))
            if result is None:
                result = card
            else:
                result = result.union(card)
        base = result

    return base

result = build({k: v[0] for k, v in PARAMS.items()})
