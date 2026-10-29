import cadquery as cq
import math

PARAMS = {
    "card_length": (85.67, 80.0, 90.0, 0.1, "mm", True, "Card length (X)"),
    "card_width": (54.06, 50.0, 58.0, 0.1, "mm", True, "Card width (Y)"),
    "thickness": (0.76, 0.4, 1.2, 0.01, "mm", True, "Card thickness"),
    "edge_chamfer": (0.15, 0.0, 0.4, 0.05, "mm", False, "Top edge chamfer"),
    "marker_count": (0, 0, 4, 1, "", False, "Reference markers count"),
}

# Measured base profile from PartSpec (already centered near origin, +X long axis)
BASE_POINTS = [[-42.337,-25.492],[-41.586,-26.328],[-40.64,-26.857],[-38.659,-27.033],[39.973,-26.996],[41.343,-26.518],[42.442,-25.288],[42.838,-23.434],[42.763,24.378],[42.403,25.417],[41.118,26.646],[39.497,27.022],[-39.429,27.016],[-41.291,26.507],[-42.383,25.409],[-42.76,24.431],[-42.831,-22.706],[-42.793,-24.211]]

# measured extents for scaling
MEASURED_LENGTH = 85.669  # 42.838 - (-42.831)
MEASURED_WIDTH = 54.055   # 27.022 - (-27.033)

def build(p: dict) -> cq.Workplane:
    # scale factors to honour PARAMS length/width
    sx = p["card_length"] / MEASURED_LENGTH
    sy = p["card_width"] / MEASURED_WIDTH

    pts = [(x * sx, y * sy) for x, y in BASE_POINTS]

    # Build solid card - mounting face on Z=0, extruded +Z to thickness
    # closed polyline defines footprint
    wp = cq.Workplane("XY")
    wp = wp.polyline(pts).close()
    solid = wp.extrude(p["thickness"])

    # optional small chamfer on top/bottom perimeter edges (does not create hollow)
    cham = float(p.get("edge_chamfer", 0))
    # clamp chamfer to < thickness/2 to avoid geometry error
    if cham > 1e-6:
        max_cham = min(cham, p["thickness"] * 0.45)
        try:
            # chamfer only horizontal perimeter edges (top and bottom)
            solid = solid.edges(">Z or <Z").chamfer(max_cham)
        except Exception:
            pass

    # topology parameter: optional reference markers (holes) - default 0 keeps solid card as per PartSpec
    n = int(p.get("marker_count", 0))
    if n > 0:
        # place small through holes along X centre line for calibration, does not affect main thickness check when n=0
        # hole diameter 3mm
        hole_d = 3.0
        # distribute along length
        span = p["card_length"] * 0.6
        if n == 1:
            xs = [0.0]
        else:
            step = span / (n - 1) if n > 1 else 0
            start = -span / 2
            xs = [start + i * step for i in range(n)]
        for x in xs:
            solid = solid.faces(">Z").workplane().pushPoints([(x, 0)]).circle(hole_d/2).cutThruAll()

    return solid

result = build({k: v[0] for k, v in PARAMS.items()})
