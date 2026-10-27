"""PartSmith golden path (validated on a synthetic photo; SAM step stubbed by a threshold mask)."""
import numpy as np, cv2, trimesh, cadquery as cq
from cadquery import cqgi
from shapely.geometry import Polygon
from scipy.spatial import cKDTree

# ---------------- 0. mat definition (printed A4 mat, 4 markers, mm) ----------------
ARUCO = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
MARKER_MM = 30.0
# marker id -> top-left corner of the marker on the mat (mm, mat frame: x right, y down, z up out of mat)
MAT_LAYOUT = {0: (10, 10), 1: (170, 10), 2: (10, 257), 3: (170, 257)}

def marker_obj_corners(mid):
    x, y = MAT_LAYOUT[mid]; s = MARKER_MM
    return np.array([[x, y], [x + s, y], [x + s, y + s], [x, y + s]], np.float32)   # TL,TR,BR,BL like detector

def make_mat_image(px_per_mm=4):
    W, H = int(210 * px_per_mm), int(297 * px_per_mm)
    img = np.full((H, W), 255, np.uint8)
    for mid, (x, y) in MAT_LAYOUT.items():
        m = cv2.aruco.generateImageMarker(ARUCO, mid, int(MARKER_MM * px_per_mm))
        img[int(y * px_per_mm):int(y * px_per_mm) + m.shape[0], int(x * px_per_mm):int(x * px_per_mm) + m.shape[1]] = m
    return img

# ---------------- 1. ArUco -> homography (image px -> mat mm) + camera pose ----------------
def detect_mat(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    det = cv2.aruco.ArucoDetector(ARUCO, cv2.aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(gray)
    assert ids is not None and len(ids) >= 2, "need >=2 markers"
    img_pts, mat_pts = [], []
    for c, i in zip(corners, ids.ravel()):
        if int(i) in MAT_LAYOUT:
            sub = cv2.cornerSubPix(gray, c.reshape(-1, 1, 2).astype(np.float32), (5, 5), (-1, -1),
                                   (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-3))
            img_pts.append(sub.reshape(4, 2)); mat_pts.append(marker_obj_corners(int(i)))
    img_pts, mat_pts = np.concatenate(img_pts), np.concatenate(mat_pts)
    H, _ = cv2.findHomography(img_pts, mat_pts, cv2.RANSAC, 1.0)
    reproj = cv2.perspectiveTransform(img_pts.reshape(-1, 1, 2), H).reshape(-1, 2)
    return H, img_pts, mat_pts, float(np.abs(reproj - mat_pts).max())

def camera_pose(img_pts, mat_pts, K, dist=None):
    obj = np.c_[mat_pts, np.zeros(len(mat_pts))].astype(np.float32)        # z=0 on the mat
    ok, rvec, tvec = cv2.solvePnP(obj, img_pts.astype(np.float32), K, dist, flags=cv2.SOLVEPNP_IPPE)
    R, _ = cv2.Rodrigues(rvec)
    return R, tvec.ravel()

# ---------------- 2. mask (SAM 3 in prod) -> contour in mm ----------------
def mask_to_contour_mm(mask, H, simplify_mm=0.2):
    m = cv2.morphologyEx(mask.astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    m = (lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
    cs, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    outer = max(cs, key=cv2.contourArea).reshape(-1, 1, 2).astype(np.float32)
    mm = cv2.perspectiveTransform(outer, H).reshape(-1, 2)
    mm = cv2.approxPolyDP(mm.reshape(-1, 1, 2), simplify_mm, True).reshape(-1, 2)
    holes = [cv2.perspectiveTransform(c.reshape(-1, 1, 2).astype(np.float32), H).reshape(-1, 2)
             for c, h in zip(cs, hier[0]) if h[3] >= 0 and cv2.contourArea(c) > 20]
    return mm, holes

def describe_for_llm(outer_mm, holes_mm):
    """Express the footprint in the PART frame (centre of minAreaRect, long side = +X, Y up) - the frame the LLM models in."""
    (cx, cy), (rw, rh), ang = cv2.minAreaRect(outer_mm.astype(np.float32))
    th = np.deg2rad(ang) + (0 if rw >= rh else np.pi / 2)
    c, s = np.cos(th), np.sin(th)
    to_local = lambda p: ((p - [cx, cy]) @ np.array([[c, -s], [s, c]])) * [1, -1]   # un-rotate, flip mat y-down -> y-up
    loc = to_local(outer_mm)
    hs = []
    for hpts in holes_mm:
        (hx, hy), r = cv2.minEnclosingCircle(hpts.astype(np.float32))
        hc = to_local(np.array([[hx, hy]]))[0]
        hs.append({"center_mm": np.round(hc, 2).tolist(), "diameter_mm": round(2 * r, 2)})
    poly = Polygon(loc)
    return {"size_mm": [round(max(rw, rh), 2), round(min(rw, rh), 2)], "area_mm2": round(poly.area, 1),
            "outline_mm": np.round(loc, 1).tolist(), "holes": hs,
            "note": "silhouette of the TOP edge seen from the camera: overestimates the footprint by ~thickness*tan(view angle)"}

# ---------------- 3. execute LLM CadQuery code (sandbox this in prod) ----------------
def run_cadquery(code, params=None):
    res = cqgi.parse(code).build(build_parameters=params or {})
    if not res.success:
        return None, f"{type(res.exception).__name__}: {res.exception}"
    shapes = [x for r in res.results for x in (r.shape.vals() if isinstance(r.shape, cq.Workplane) else [r.shape])]
    shape = cq.Compound.makeCompound(shapes)
    if not shape.isValid():
        return None, "invalid solid"
    v, f = shape.tessellate(0.01, 0.1)
    return trimesh.Trimesh(np.array([p.toTuple() for p in v]), np.array(f), process=True), None

# ---------------- 4. render silhouette from the photo's camera (no GL) ----------------
def render_silhouette(mesh, K, R, t, h, w):
    Xc = (R @ mesh.vertices.T + t.reshape(3, 1)).T
    uv = (K @ Xc.T).T; uv = uv[:, :2] / uv[:, 2:3]
    tris = np.round(uv[mesh.faces] * 16).astype(np.int32)
    mask = np.zeros((h, w), np.uint8)
    for tri in tris:                                   # per-triangle: fillPoly on a list uses even-odd => overlaps cancel!
        cv2.fillConvexPoly(mask, tri, 255, cv2.LINE_8, shift=4)
    return mask > 0

# ---------------- 5. metrics ----------------
def mask_iou(a, b):
    return float((a & b).sum() / max((a | b).sum(), 1))

def contour_distances_mm(mask_a, mask_b, H):
    """symmetric Hausdorff / mean / 95th pct between mask boundaries, measured on the mat plane (mm)."""
    def edge_mm(m):
        cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        p = np.concatenate([c.reshape(-1, 2) for c in cs]).astype(np.float32)
        return cv2.perspectiveTransform(p.reshape(-1, 1, 2), H).reshape(-1, 2)
    A, B = edge_mm(mask_a), edge_mm(mask_b)
    dab, _ = cKDTree(B).query(A); dba, _ = cKDTree(A).query(B)
    return {"hausdorff_mm": float(max(dab.max(), dba.max())),
            "hd95_mm": float(max(np.percentile(dab, 95), np.percentile(dba, 95))),
            "mean_mm": float((dab.mean() + dba.mean()) / 2)}

# ---------------- 4b. place the CAD part (modelled centred at origin, Z up, long axis = X) on the mat ----------------
FLIP = np.diag([1.0, -1.0, -1.0, 1.0])     # CAD (z up) -> mat frame (x right, y down, z into the table)

def placement(cx, cy, theta):
    T = trimesh.transformations.translation_matrix([cx, cy, 0])
    Rz = trimesh.transformations.rotation_matrix(theta, [0, 0, 1])
    return T @ Rz @ FLIP

def register_on_mat(mesh_cad, outer_mm, mask, K, R, t, h, w):
    """init from minAreaRect of the measured footprint, try the 4 symmetric yaws, refine with Nelder-Mead on IoU."""
    from scipy.optimize import minimize
    (cx, cy), (rw, rh), ang = cv2.minAreaRect(outer_mm.astype(np.float32))
    base = np.deg2rad(ang) + (0 if rw >= rh else np.pi / 2)
    def neg_iou(p):
        m = mesh_cad.copy(); m.apply_transform(placement(*p))
        return -mask_iou(render_silhouette(m, K, R, t, h, w), mask)
    best = min((neg_iou([cx, cy, base + k * np.pi / 2]), [cx, cy, base + k * np.pi / 2]) for k in range(4))
    r = minimize(neg_iou, best[1], method="Nelder-Mead",
                 options={"xatol": 0.05, "fatol": 1e-4, "maxiter": 60, "initial_simplex":
                          np.array(best[1]) + np.array([[0, 0, 0], [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.02]])})
    return placement(*r.x), -r.fun

# ======================= synthetic self-test =======================
if __name__ == "__main__":
    import time
    GT_CODE = """
import cadquery as cq
length = 60.0
width = 30.0
thickness = 4.0
hole_d = 8.0
result = (cq.Workplane("XY").rect(length, width).extrude(thickness)
          .edges("|Z").fillet(3.0).faces(">Z").workplane().hole(hole_d))
show_object(result)
"""
    gt_cad, err = run_cadquery(GT_CODE); assert err is None, err
    gt_mesh = gt_cad.copy(); gt_mesh.apply_transform(placement(100, 150, np.deg2rad(30)))   # unknown to the pipeline
    # synthetic phone camera: 3000x4000, f=3200 px, ~400 mm above the mat, tilted
    w, h = 3000, 4000
    K = np.array([[3200, 0, w / 2], [0, 3200, h / 2], [0, 0, 1.0]])
    R, _ = cv2.Rodrigues(np.array([0.15, -0.1, 0.05])); t = -R @ np.array([105, 148, -400.0])
    S = np.diag([1 / 8, 1 / 8, 1])
    photo = cv2.cvtColor(cv2.warpPerspective(make_mat_image(8), K @ np.c_[R[:, :2], t] @ S, (w, h), borderValue=200), cv2.COLOR_GRAY2BGR)
    photo[render_silhouette(gt_mesh, K, R, t, h, w)] = (40, 90, 200)

    # ---- pipeline ----
    H, img_pts, mat_pts, err_mm = detect_mat(photo)
    Rc, tc = camera_pose(img_pts, mat_pts, K)                  # K from EXIF / calibration in prod
    print("homography reproj err mm:", round(err_mm, 4), "| pose dt mm:", round(float(np.abs(tc - t).max()), 3))
    sam_mask = np.all(photo == (40, 90, 200), axis=2)          # <- SAM 3 mask in prod
    outer, holes = mask_to_contour_mm(sam_mask, H)
    spec = describe_for_llm(outer, holes)
    print("LLM spec: size", spec["size_mm"], "holes", spec["holes"], "(parallax: footprint of a 4 mm-thick part)")
    for name, code in [("draft", GT_CODE.replace("hole_d = 8.0", "hole_d = 7.0").replace("width = 30.0", "width = 31.0")),
                       ("fixed", GT_CODE)]:
        t0 = time.time()
        cand, err = run_cadquery(code); assert err is None, err
        T, iou = register_on_mat(cand, outer, sam_mask, K, Rc, tc, h, w)
        cand.apply_transform(T)
        d = contour_distances_mm(render_silhouette(cand, K, Rc, tc, h, w), sam_mask, H)
        print(f"{name}: IoU={iou:.4f} hausdorff={d['hausdorff_mm']:.3f}mm hd95={d['hd95_mm']:.3f}mm mean={d['mean_mm']:.3f}mm ({time.time()-t0:.1f}s)")
