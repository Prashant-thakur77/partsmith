# data/synthetic — everything here is SYNTHETIC

Nothing in this folder is a real photo. Every image is a render made by `tools/synth` from a CAD mesh and a known
camera, so its ground truth is exact. The JPEGs say so in their EXIF `ImageDescription`, every `meta.json` has
`"origin": "synthetic"`, and every `gt.yaml` has `gt_source: synthetic_exact`. Never mix these numbers with real
photos (reference objects vs their published specs, or real parts vs a ruler); `eval/` reports each source on its own.

## Layout

| Path | What | In git |
|---|---|---|
| `samples/` | demo set: 12 template parts (every family template at least once, screen and paper mats, two hard cases) + the 4 reference objects, 2000×1500 JPEGs | yes |
| `bench/` | the measurement bench (`eval/measure_only.py` renders it from a seed when missing), 3000×2250 JPEGs | no (gitignored) |
| `bench_manifest.json` | seeds, settings and sha256 of every bench file, so the bench can be re-rendered and checked | yes |

## One sample = one folder

- `top.jpg` — the part lying on a virtual screen mat (backlit, colour cast, pixel grid, bezel, optional glare/moiré)
  or on the plain-paper mat (fibre texture, lamp gradient, soft shadow); phone-like camera 220–420 mm above the
  mat, tilt 0–18°, ≈ 26 mm-equivalent lens (also written to EXIF), defocus, sensor noise, JPEG.
- `side.jpg` — the same part laid on its side (turned 90° about its long axis) so its thickness faces the camera.
  Not rendered for the ID-1 card and the AA cell.
- `meta.json` — only what a user would know: id, title, kind (`template` / `reference_object`), origin, mat id,
  family hint, intent, `user_thickness_mm` (the thickness read off a ruler, nearest 0.5 mm; the published thickness
  for reference objects), difficulty, augmentations, seed. Agents may read it.
- `gt.yaml` — exact ground truth, **for scorers only** (`eval/`, tests; never shown to an agent): template and params
  (or the reference object and its spec table), named dimensions in mm, camera K/R/t per view, the part's placement on
  the mat, the mat id.

Named dimensions are computed from the mesh, never from a render:

- `length`, `width` (top view): sides of the minimum-area rectangle of the orthographic footprint;
- `hole_k.diameter` (top view): openings you can see through from straight above, with their centres on the mat
  (used to match measured holes by position);
- `thickness` (side view): short side of the footprint of the part laid on its side.

## Presets

`clean`, `tilt` (12–18°), `blur` (σ 1.4–2.4 px), `glare` (reflection streak on the screen), `moire` (strong pixel
grid + interference fringes), `low-light` (under-exposed, noisy, warm), `white-part` (white / light-grey / beige part
on a white stage — hard on purpose), `paper` (plain-paper mat).

## Regenerate

```bash
uv run python -m tools.synth --demo --out data/synthetic/samples                  # this demo set
uv run python -m tools.synth --out data/synthetic/bench --n 60 --n-reference 20 --seed 7 --jobs 4
```

Same seed → same bytes on the same library versions (OpenCV, Pillow/libjpeg, the CAD kernel's tessellation).
