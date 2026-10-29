import cadquery as cq
import math

FAMILY = "cover"
TITLE = "Battery compartment cover"
SUMMARY = "Thin battery door from measured polyline with L-shaped snap latch on left edge."
TAGS = ["battery cover", "battery door", "lid", "snap-fit"]
MEASURE_MAP = {"length": "length", "width": "width", "thickness": "thickness"}

# Measured polyline points in mm, centred near origin, long axis +X
PTS = [(25.385,-15.248),(25.573,-9.295),(25.276,-8.662),(24.947,-8.495),(22.977,-8.286),(22.878,-4.644),(23.023,-3.729),(24.049,-3.423),(25.079,-3.644),(25.505,-3.044),(25.738,2.632),(25.201,3.318),(23.109,3.53),(22.848,4.718),(22.969,7.982),(23.803,8.327),(25.391,8.292),(25.559,14.178),(25.241,15.077),(24.541,15.337),(23.45,15.257),(23.047,15.493),(22.867,17.845),(22.522,18.497),(20.915,18.89),(-0.718,18.779),(-2.598,18.969),(-3.278,18.796),(-9.988,18.883),(-10.774,18.713),(-20.145,18.802),(-20.525,18.966),(-22.745,18.709),(-24.25,18.068),(-25.314,16.625),(-25.673,15.533),(-25.491,13.715),(-25.731,12.333),(-25.56,11.133),(-25.745,8.509),(-25.539,7.921),(-25.745,4.069),(-25.554,-4.578),(-25.741,-5.894),(-25.577,-6.626),(-25.691,-14.598),(-25.559,-16.026),(-25.072,-17.092),(-23.678,-18.44),(-22.6,-18.871),(-20.588,-18.969),(-19.3,-18.783),(-11.005,-18.953),(-9.972,-18.715),(-8.047,-18.895),(-6.187,-18.692),(-4.734,-18.953),(0.169,-18.772),(5.452,-18.913),(6.017,-18.736),(9.885,-18.957),(22.311,-18.806),(22.89,-17.798),(22.98,-15.616)]

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "thickness": (1.5, 1.0, 3.0, 0.05, "mm", True, "Door thickness"),
    "latch_height": (2.6, 2.0, 6.0, 0.1, "mm", True, "Latch height above inner face"),
    "latch_overhang": (1.5, 0.5, 3.5, 0.05, "mm", True, "Latch hook overhang"),
    "latch_thickness": (1.2, 0.8, 2.0, 0.05, "mm", True, "Latch wall thickness"),
    "latch_width": (12.0, 6.0, 20.0, 0.1, "mm", True, "Latch width along Y"),
    "clearance": (0.2, 0.0, 0.5, 0.05, "mm", True, "XY clearance for FDM fit"),
    "groove_count": (3, 0, 12, 1, "", False, "Grip grooves (outer face)"),
    "corner_radius": (1.5, 0.0, 3.0, 0.1, "mm", False, "Plate edge fillet radius"),
}

def build(p: dict) -> cq.Workplane:
    t = p["thickness"]
    lh = p["latch_height"]
    over = p["latch_overhang"]
    lt = p["latch_thickness"]
    lw = p["latch_width"]
    groove_count = int(p["groove_count"])

    # Base plate from measured polyline, mounting face on Z=0, extruded +Z
    plate = cq.Workplane("XY").polyline(PTS).close().extrude(t)

    # Light edge fillet for printability, keep mounting face sharp
    r = min(p["corner_radius"], t * 0.9)
    if r > 0.2:
        try:
            plate = plate.edges("|Z").fillet(r)
        except Exception:
            pass

    # Grip grooves on outer face z=0, keep >=0.9mm material
    gd = min(0.5, t - 0.9)
    if groove_count > 0 and gd > 0.1:
        # grooves across width (Y direction long), spaced along X
        # estimate length along X from points bounds
        xs = [ -10 + i * 4.0 for i in range(groove_count) ]
        cut = cq.Workplane("XY").workplane(offset=-1).pushPoints([(x, 0) for x in xs]).rect(1.0, 28.0)
        plate = plate.cut(cut.extrude(1 + gd))

    # L-shaped snap latch on left edge (anchor left_edge, negative X side)
    left_x = min(x for x, y in PTS)
    # left edge Y center - find approximate mid Y at left edge
    # use average Y of leftmost points
    left_ys = [y for x, y in PTS if x < left_x + 2.0]
    y_mid = sum(left_ys) / len(left_ys) if left_ys else 0.0
    # clamp latch width inside plate
    width_est = 37.5
    lw = min(lw, width_est - 4.0)

    # vertical stem: sits on inner face +Z, flush to left edge interior
    # stem X from left_x to left_x+lt (inside), Y centered on y_mid, Z from t to t+lh
    stem = cq.Workplane("XY").box(lt, lw, lh, centered=False).translate((left_x, y_mid - lw/2, t))
    # horizontal hook lip at top extending outward -X by overhang
    hook_t = 1.0
    hook_t = min(hook_t, lh - 0.4)
    hook_x0 = left_x - over
    hook_x1 = left_x + lt
    hook_len_x = hook_x1 - hook_x0
    hook = cq.Workplane("XY").box(hook_len_x, lw, hook_t, centered=False).translate((hook_x0, y_mid - lw/2, t + lh - hook_t))

    result = plate.union(stem).union(hook)
    return result

result = build({k: v[0] for k, v in PARAMS.items()})
