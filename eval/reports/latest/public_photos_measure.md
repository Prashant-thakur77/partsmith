# Public photos: measure only (no model)

Composites, not phone captures: a real object cut out of a public photograph by code and pasted on our rendered screen mat at a scale set from one published dimension (the long side). That dimension is marked set_by_construction and excluded from every error. The mat, the camera and the light on the mat are rendered, the cut-out is flat, has no walls and casts no shadow. Counted as 0 real photos measured. It says nothing about a phone photographing a laptop screen.

16 composites from 13 public photographs; capture gate passed 16/16. Held-out dimensions on accepted photos: mean abs error **0.432 mm** (95 % CI 0.296 to 0.603, bootstrap over samples), median 0.302, max 1.675, n = 21; every held-out dimension within 0.5 mm on 10/16 photos.

| object | photos | held-out dims | mean abs mm | max abs mm | within 0.5 mm |
|---|---:|---:|---:|---:|---:|
| aa_cell | 1 | 1 | 1.675 | 1.675 | 0 |
| id1_card | 1 | 1 | 0.267 | 0.267 | 1 |
| microsd_card | 2 | 4 | 0.309 | 0.491 | 4 |
| sd_card | 8 | 8 | 0.341 | 0.832 | 6 |
| us_dime | 1 | 2 | 0.592 | 0.962 | 1 |
| yen_5 | 3 | 5 | 0.398 | 0.757 | 4 |

Read straight from the cut-out, before the mat: mean abs 0.322 mm (n = 19).

| sample | object | gate | dimension | published mm | measured mm | error mm | counted |
|---|---|---|---|---:|---:|---:|---|
| sd_card-1 | sd_card | pass | length | 32.0 | 32.03 | 0.03 | no: set by construction |
| sd_card-1 | sd_card | pass | width | 24.0 | 23.966 | -0.034 | yes |
| sd_card-2 | sd_card | pass | length | 32.0 | 31.961 | -0.039 | no: set by construction |
| sd_card-2 | sd_card | pass | width | 24.0 | 23.834 | -0.166 | yes |
| sd_card-3 | sd_card | pass | length | 32.0 | 31.928 | -0.072 | no: set by construction |
| sd_card-3 | sd_card | pass | width | 24.0 | 23.983 | -0.017 | yes |
| sd_card-4 | sd_card | pass | length | 32.0 | 31.912 | -0.088 | no: set by construction |
| sd_card-4 | sd_card | pass | width | 24.0 | 24.473 | 0.473 | yes |
| sd_card-6 | sd_card | pass | length | 32.0 | 31.477 | -0.523 | no: set by construction |
| sd_card-6 | sd_card | pass | width | 24.0 | 23.751 | -0.249 | yes |
| sd_card-8 | sd_card | pass | length | 32.0 | 31.965 | -0.035 | no: set by construction |
| sd_card-8 | sd_card | pass | width | 24.0 | 24.832 | 0.832 | yes |
| microsd_card-1 | microsd_card | pass | length | 15.0 | 15.257 | 0.257 | yes |
| microsd_card-1 | microsd_card | pass | width | 11.0 | 11.467 | 0.467 | yes |
| sd_card-9 | sd_card | pass | length | 32.0 | 31.69 | -0.31 | no: set by construction |
| sd_card-9 | sd_card | pass | width | 24.0 | 23.35 | -0.65 | yes |
| microsd_card-2 | microsd_card | pass | length | 15.0 | 14.978 | -0.022 | yes |
| microsd_card-2 | microsd_card | pass | width | 11.0 | 10.509 | -0.491 | yes |
| us_dime-1 | us_dime | pass | length | 17.91 | 17.689 | -0.221 | yes |
| us_dime-1 | us_dime | pass | width | 17.91 | 16.948 | -0.962 | yes |
| yen_5-1 | yen_5 | pass | length | 22.0 | 21.876 | -0.124 | no: set by construction |
| yen_5-1 | yen_5 | pass | width | 22.0 | 21.243 | -0.757 | yes |
| yen_5-1 | yen_5 | pass | hole_1.diameter | 5.0 | 4.542 | -0.458 | yes |
| yen_5-2 | yen_5 | pass | length | 22.0 | 21.963 | -0.037 | no: set by construction |
| yen_5-2 | yen_5 | pass | width | 22.0 | 21.758 | -0.242 | yes |
| yen_5-2 | yen_5 | pass | hole_1.diameter | 5.0 | 5.302 | 0.302 | yes |
| yen_5-3 | yen_5 | pass | length | 22.0 | 22.009 | 0.009 | no: set by construction |
| yen_5-3 | yen_5 | pass | width | 22.0 | 21.77 | -0.23 | yes |
| id1_card-1 | id1_card | pass | length | 85.6 | 85.425 | -0.175 | no: set by construction |
| id1_card-1 | id1_card | pass | width | 53.98 | 53.713 | -0.267 | yes |
| aa_cell-1 | aa_cell | pass | length | 50.5 | 37.016 | -13.484 | no: set by construction |
| aa_cell-1 | aa_cell | pass | width | 14.5 | 12.825 | -1.675 | yes |
| sd_card-10 | sd_card | pass | length | 32.0 | 31.951 | -0.049 | no: set by construction |
| sd_card-10 | sd_card | pass | width | 24.0 | 23.693 | -0.307 | yes |

Failures:
- yen_5-3: missed hole_1.diameter
