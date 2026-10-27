# services/metrology — photo → millimetres

Deterministic measurement code. No model output decides anything here; SAM 3.1 masks arrive through an injected
callable and are cleaned and measured by code. Units are mm, angles deg.

## Pipeline

```
photo ─▶ detect_mat (ArUco ring → mat id, sub-pixel corners, RANSAC homography image→mat mm)
      ─▶ estimate_pose (K: calibration file > EXIF 35 mm focal > single-view estimate; IPPE + LM)
      ─▶ Segmenter.segment (ProviderSegmenter = SAM 3.1 prompt ladder + crop re-run; ThresholdSegmenter = plain stage)
      ─▶ refine_mask + mask_contour_subpx (sub-pixel outer/hole contours)
      ─▶ footprint in mat mm (mat plane ∩ top-face plane when the thickness is known)
      ─▶ features (part frame, outline, holes, slots, symmetry, σ per value) ─▶ MeasureResult + overlay PNG
run_gate checks the photo (markers, reprojection, blur, coverage, tilt, exposure, glare, moiré, scale) with one
actionable sentence per check.
```

| Module | Entry points |
|---|---|
| `mats.py` | `get_mat`, `all_mats`, `identify`, `marker_corners_mm`, `render_mat`, `layout_json`, `fitting_mats` |
| `card.py` | `card_px_per_mm` (ID-1 card match → CSS/device px per mm + σ), `ruler_scale_correction` |
| `calibrate.py` | `detect_mat`, `estimate_pose`, `plane_homography`, `height_scale`, `rectify`, `calibration_from` |
| `capture_gate.py` | `run_gate(img, det, mask=None, *, pose=None) -> CaptureReport` |
| `segment.py` | `Segmenter`, `ThresholdSegmenter`, `ProviderSegmenter(call)`, `refine_mask`, `mask_contour_subpx` |
| `features.py` | `analyse_footprint`, `build_measurements`, `fit_circle`, `fit_slot`, `symmetry_axis`, `SigmaModel` |
| `measure.py` | `measure_photo(img, view, *, segmenter, thickness_mm=None, K=None, origin=...) -> MeasureOutput` |
| `fit_check.py` | `fit_outline_for(outline_part, holes, mat_id)`, `fit_check(photo, mat_id, outline_mm, holes)` |
| `testing.py` | synthetic scenes with exact ground truth: `camera_above`, `PrismPart`, `render_scene`, augmentations |

## Mats

Rings of `DICT_5X5_100` markers around a plain stage; each mat owns a disjoint id block, so the photo tells which mat it
is. `uv run python -m tools.mat.make_mat --web` writes `apps/web/public/mats/<mat_id>.json` (`MatLayout`, bits include
the black border, 1 = white) and `index.json`; `--pdf out.pdf` writes the plain-paper A4 mat with a 50.0 mm check ruler.

| mat | for | ids |
|---|---|---|
| `screen-s` | phone screen | 0–19 |
| `screen-m` | tablet / 13" laptop | 25–48 |
| `screen-l` | 15" laptop | 50–73 |
| `paper-a4` | plain paper, printed at 100 % | 75–96 |

## Height (parallax) correction

A part's top edges are closer to the camera than the mat. With the thickness known, contours are mapped onto the mat
plane and onto the plane at the top-face height (`plane_homography`: the fitted mat homography followed by the
homothety s = (Zc − h)/Zc about the camera nadir) and the two footprints are intersected. For prisms with vertical walls
that recovers the true outline on both the near (bottom edge visible) and far (top edge visible) sides, and keeps
through-holes round. `height_scale(Zc, h)` is reported as `height_correction_scale`.

## Fit check

The web page draws the `fit-outline` (mat frame) in `FIT_OUTLINE_RGB` (#E0218A); the threshold segmenter treats that
colour (and its anti-aliased blend with the stage) as background. The part is aligned to the outline with a small rigid
move, then compared: green ≤ 0.35 mm, amber ≤ 0.8 mm, red beyond; pass = 95 % within 0.5 mm, max ≤ 1.0 mm, IoU ≥ 0.95,
holes within 0.5 mm. The reasoning behind these bounds is in the `fit_check.py` docstring.

## Tests

`uv run pytest services/metrology tools/mat tools/calib` — synthetic photos rendered from known K, R, t (exact
anti-aliased coverage), including an 8 mm-thick part where the uncorrected measurement must be worse than the corrected
one. Synthetic results are evidence for the geometry only; real-photo accuracy is measured by the benches in `eval/`.
