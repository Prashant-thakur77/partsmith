# Real-camera scale check (public photos of printed boards)

Measures how well a flat-plane marker fit holds on real lenses and real printed paper. It says nothing about a phone photographing a laptop screen, nothing about measuring a part, and these photos are not counted as real photos measured. The boards' printed size is unknown, so all numbers are relative; the mm figure is the relative error applied to a 100 mm span on our mat, not a measured length.

**Layout confirmed by its outer markers:** 0.138 % of span (95 % CI 0.108 to 0.178), median 0.114 %, max 0.452 %; n = 48 corners on 12 markers in 2 photos (scale-2, scale-3); over a 100 mm span on our mat 0.138 mm (CI 0.108 to 0.178). CI: percentile bootstrap over held-out markers, 2000 resamples, seeded; not over photos.

Every photo with its documented layout, as written: 0.578 % of span (95 % CI 0.424 to 0.73), median 0.24 %, max 1.65 %; n = 108 corners on 27 markers in 3 photos (scale-1, scale-2, scale-3); over a 100 mm span on our mat 0.578 mm (CI 0.424 to 0.73).

With the grid board's gap ratio fitted on outer markers only: 0.106 % of span (95 % CI 0.087 to 0.13), median 0.085 %, max 0.452 %; n = 108 corners on 27 markers in 3 photos (scale-1, scale-2, scale-3); over a 100 mm span on our mat 0.106 mm (CI 0.087 to 0.13).

scale-1: the documented layout fits only 24/80 outer corners, so it does not describe this print (0.9292 % held-out as written). The outer markers alone give a gap ratio of 0.2 (0.0794 % held-out). That photo is left out of the headline because its layout is estimated, not documented

| photo | size px | fit markers | outer inliers | held-out corners | mean % | max % | mean px | 1 px = % |
|---|---|---|---|---:|---:|---:|---:|---:|
| scale-1 | 640×480 | 20 | 24/80 | 60 | 0.9292 | 1.65 | 2.882 | 0.3224 |
| scale-2 | 640×480 | 10 | 39/40 | 28 | 0.1131 | 0.2678 | 0.396 | 0.2853 |
| scale-3 | 640×480 | 8 | 31/32 | 20 | 0.1736 | 0.452 | 0.579 | 0.2999 |

Photos left out:
- scale-x1: loose markers with no documented layout: no held-out truth
- scale-x2: marker diamonds with no documented layout between them: no held-out truth

Control: on scale-2 a wrong marker size in the layout gives 1.2428 % against 0.1131 % with the documented one.

Control: on scale-3 a wrong marker size in the layout gives 1.4487 % against 0.1736 % with the documented one.
