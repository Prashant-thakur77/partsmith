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

## Through-holes in thick parts

From above, a through-hole shows the mat only where its bottom opening (z = 0) and its top opening (z = h, shifted by
parallax) overlap — a lens when the camera is off to one side. With the thickness and pose known, each see-through
region is fitted as a vertical cylinder (`features.fit_see_through_hole`): the residual of a boundary point is
max(|q − c| − r, |q − c'| − r/s), c' and r/s being the top opening projected onto the mat plane. σ combines the fit
statistics with a refit at h ± 0.3 mm; `evidence.note` says "see-through fit, h=… mm". Small see-through regions are
kept when the expected parallax shift is ≥ 0.1 mm. Bores that hide the mat completely are reported in `notes` as a
"possible hidden hole" (a compact wall-coloured patch inside the top face), never invented as a hole.

## Stage colour, contrast and shadows

`mats.STAGE_COLOURS = {"light": "#FFFFFF", "dark": "#303030"}`: the screen mat may fill its stage with either (the
marker ring stays black on white). The threshold segmenter models whatever uniform stage colour it sees. The gate's
`contrast` check fails with "The part blends into the background — switch the screen mat to the dark stage (or use a
darker surface)" when the part's colour is the stage colour slightly darkened (white, off-white, light grey on white),
when the outline has long stretches without contrast, when the segmentation fell apart into pieces, or when the mask is
implausibly ragged. Cast shadows (same chroma as the stage, 50–100 % of its brightness — a desk-lamp shadow with room
light filling in is rarely darker — and no sharp structure) are removed unless the part itself has that colour, and only
where a real edge separates part and shadow; edges next to a shadow are located against the shadow, not the bare stage.
Shadow-coloured parts (white, light and mid grey on a white stage) fail the contrast check. On any stage, the mask grows
from the most contrasting faces into everything connected that differs from the stage by more than the noise floor and
is not shadow-coloured, so a light part's dimmer shaded walls on the dark stage stay part; edges are located at 50 % of
the local inside level, not of the part's median contrast.

## Side views, round profiles, tall features

- Side view (part on its side): pass the top view's width as `thickness_mm`. A thin, tall object keeps only a small
  share of its photo outline after the height correction; that is accepted (guard 5 % for side views, 25 % for top).
  The correction assumes the part is equally tall along the whole profile; a lower feature on the far side reads short.
  When the corrected and uncorrected thickness differ, `notes` gives both bounds and σ covers the range.
- `profile="round"`: a cylinder lying on its curved side (AA cell, wheel on its tread), `thickness_mm` = diameter.
  Curved sides come from silhouette rays tangent to the cylinder (mid-height plane, corrected by r(1/cos θ − 1)); the
  flat ends from the prism outline.
- `stated_thickness_mm` on a side view adds a note when the part stands clearly taller than the stated plate thickness.

## Camera-frame outputs

`MeasureOutput.K`, `.R`, `.t_mm` (from the pose), `.photo_mask` (full frame), `.part_to_mat`, `.H_top` and
`.top_px_per_mm` (local image px per mm at the part centre on the plane used for measuring).

## Fit check

The web page draws the `fit-outline` (mat frame) in `FIT_OUTLINE_RGB` (#E0218A); the threshold segmenter treats that
colour (and its anti-aliased blend with the stage) as background. The part is aligned to the outline with a small rigid
move, then compared: green ≤ 0.35 mm, amber ≤ 0.8 mm, red beyond; pass = 95 % within 0.5 mm, max ≤ 1.0 mm, IoU ≥ 0.95,
holes within 0.5 mm. The reasoning behind these bounds is in the `fit_check.py` docstring.

## Tests

`uv run pytest services/metrology tools/mat tools/calib` — synthetic photos rendered from known K, R, t (exact
anti-aliased coverage), including an 8 mm-thick part where the uncorrected measurement must be worse than the corrected
one. Synthetic results are evidence for the geometry only; real-photo accuracy is measured by the benches in `eval/`.
