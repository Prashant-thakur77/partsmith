# measure_only bench — 2026-10-27

Photo → millimetres only: `measure_photo` with the deterministic threshold segmenter (no model, no keys). Errors are |measured − ground truth| in mm. **Accepted** = photos that passed the capture gate (the app asks for a retake otherwise); rejected photos are listed under failures. Sources are never merged.

Synthetic bench: seed 7, n = 60 template samples + 20 reference-object renders, dataset sha256 `a576c6980c08ae02…`. All synthetic.

## Phase 1 exit gate (mean abs error ≤ 0.4 mm, accepted photos)

- synthetic bench: mean 0.628 mm over N = 216 dims → **FAIL**
- reference objects (reference_spec (published spec; synthetic render of the nominal model)): mean 0.194 mm over N = 40 dims → **PASS**
- overall: **FAIL**

## synthetic

Ground truth: synthetic_exact (template mesh, exact).

Photos: 120 (mat + part detected: 120; capture gate passed: 94/120 = 78 % [0.70, 0.85]).

| dims | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| accepted photos | 216 | 0.628 [0.388, 0.966] | 0.153 | 1.190 | 29.707 | 70 % | 80 % | -0.201 |
| all detected photos | 272 | 1.089 [0.678, 1.578] | 0.171 | 1.436 | 36.308 | 65 % | 75 % | -0.475 |

- pass@0.3 mm (every named dim of an accepted photo within 0.3 mm; a missed dim fails): 39/94 = 41 % [0.32, 0.52]
- pass@0.5 mm (every named dim of an accepted photo within 0.5 mm; a missed dim fails): 54/94 = 57 % [0.47, 0.67]

| by dimension | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| hole Ø | 75 | 0.138 [0.115, 0.164] | 0.098 | 0.298 | 0.449 | 91 % | 100 % | -0.069 |
| side:thickness | 47 | 0.731 [0.477, 1.006] | 0.396 | 2.587 | 3.630 | 43 % | 60 % | -0.704 |
| top:length | 47 | 1.000 [0.218, 2.399] | 0.128 | 1.103 | 29.707 | 77 % | 79 % | -0.421 |
| top:width | 47 | 0.938 [0.498, 1.531] | 0.254 | 2.779 | 10.502 | 60 % | 68 % | 0.311 |

| by profile | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| side: flat | 21 | 0.309 [0.212, 0.410] | 0.242 | 0.647 | 0.853 | 52 % | 76 % | -0.280 |
| side: tall features | 26 | 1.072 [0.665, 1.535] | 0.586 | 3.062 | 3.630 | 35 % | 46 % | -1.046 |
| top: flat | 80 | 0.172 [0.140, 0.206] | 0.128 | 0.338 | 0.798 | 82 % | 95 % | -0.137 |
| top: tall features | 89 | 0.984 [0.436, 1.734] | 0.138 | 1.909 | 29.707 | 74 % | 76 % | 0.006 |

| by preset | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| blur | 29 | 0.684 [0.261, 1.203] | 0.172 | 1.835 | 5.315 | 72 % | 76 % | 0.395 |
| clean | 37 | 0.372 [0.217, 0.571] | 0.136 | 0.960 | 3.037 | 70 % | 76 % | 0.206 |
| glare | 35 | 0.440 [0.162, 0.806] | 0.112 | 0.590 | 4.953 | 74 % | 86 % | -0.010 |
| low-light | 31 | 0.310 [0.124, 0.571] | 0.086 | 1.098 | 3.055 | 81 % | 87 % | -0.177 |
| moire | 4 | 0.596 [0.082, 1.353] | 0.276 | 1.375 | 1.771 | 50 % | 75 % | 0.340 |
| paper | 38 | 0.362 [0.215, 0.564] | 0.180 | 0.453 | 2.749 | 68 % | 89 % | -0.279 |
| tilt | 32 | 0.526 [0.270, 0.847] | 0.178 | 1.055 | 3.251 | 62 % | 69 % | -0.295 |
| white-part | 10 | 4.418 [0.342, 10.357] | 0.265 | 12.422 | 29.707 | 60 % | 60 % | -3.803 |

| by family / object | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| bracket | 13 | 1.408 [0.607, 2.337] | 0.413 | 3.748 | 5.315 | 46 % | 54 % | 0.991 |
| cable_clip | 21 | 2.164 [0.212, 5.475] | 0.157 | 1.282 | 29.707 | 71 % | 76 % | -1.803 |
| clip | 16 | 0.610 [0.208, 1.161] | 0.157 | 1.742 | 3.587 | 69 % | 69 % | 0.444 |
| cover | 18 | 0.937 [0.377, 1.578] | 0.084 | 3.059 | 3.630 | 67 % | 67 % | -0.849 |
| hinge | 18 | 0.258 [0.140, 0.396] | 0.142 | 0.647 | 0.926 | 72 % | 78 % | 0.087 |
| hook | 25 | 0.799 [0.394, 1.294] | 0.177 | 2.123 | 4.953 | 56 % | 64 % | 0.197 |
| knob | 18 | 0.169 [0.123, 0.216] | 0.166 | 0.291 | 0.316 | 94 % | 100 % | -0.148 |
| latch | 24 | 0.199 [0.135, 0.265] | 0.138 | 0.407 | 0.647 | 71 % | 96 % | -0.083 |
| spacer | 12 | 0.167 [0.079, 0.279] | 0.093 | 0.424 | 0.678 | 83 % | 92 % | -0.106 |
| wheel | 51 | 0.214 [0.162, 0.278] | 0.153 | 0.568 | 0.853 | 73 % | 86 % | -0.212 |

| by mat | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| paper-a4 | 55 | 1.131 [0.331, 2.466] | 0.263 | 1.200 | 29.707 | 65 % | 80 % | -0.872 |
| screen-l | 60 | 0.492 [0.264, 0.769] | 0.114 | 1.409 | 4.953 | 75 % | 82 % | 0.086 |
| screen-m | 101 | 0.436 [0.285, 0.619] | 0.100 | 1.021 | 5.315 | 70 % | 78 % | -0.006 |

## reference_objects_synthetic

Ground truth: reference_spec (published spec; synthetic render of the nominal model).

Photos: 30 (mat + part detected: 30; capture gate passed: 24/30 = 80 % [0.63, 0.90]).

| dims | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| accepted photos | 40 | 0.194 [0.124, 0.275] | 0.087 | 0.599 | 1.161 | 85 % | 88 % | -0.059 |
| all detected photos | 50 | 0.176 [0.119, 0.244] | 0.074 | 0.402 | 1.161 | 86 % | 90 % | -0.052 |

- pass@0.3 mm (every named dim of an accepted photo within 0.3 mm; a missed dim fails): 20/24 = 83 % [0.64, 0.93]
- pass@0.5 mm (every named dim of an accepted photo within 0.5 mm; a missed dim fails): 20/24 = 83 % [0.64, 0.93]
- inside the spec's accepted range: 25/40 = 62 % [0.47, 0.76]

| by dimension | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| side:thickness | 8 | 0.120 [0.062, 0.188] | 0.100 | 0.253 | 0.289 | 100 % | 100 % | 0.014 |
| top:length | 16 | 0.266 [0.116, 0.447] | 0.071 | 0.710 | 1.161 | 75 % | 75 % | -0.130 |
| top:width | 16 | 0.157 [0.088, 0.243] | 0.087 | 0.316 | 0.655 | 88 % | 94 % | -0.024 |

| by preset | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| blur | 8 | 0.299 [0.177, 0.446] | 0.251 | 0.612 | 0.655 | 75 % | 75 % | -0.013 |
| clean | 10 | 0.185 [0.098, 0.305] | 0.151 | 0.325 | 0.645 | 90 % | 90 % | -0.048 |
| glare | 10 | 0.133 [0.041, 0.284] | 0.053 | 0.248 | 0.775 | 90 % | 90 % | -0.065 |
| moire | 2 | 0.066 [0.065, 0.067] | 0.066 | 0.067 | 0.067 | 100 % | 100 % | 0.066 |
| tilt | 10 | 0.204 [0.057, 0.430] | 0.081 | 0.448 | 1.161 | 80 % | 90 % | -0.125 |

| by family / object | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| aa_cell | 8 | 0.578 [0.381, 0.795] | 0.619 | 0.891 | 1.161 | 25 % | 38 % | -0.578 |
| id1_card | 8 | 0.103 [0.068, 0.141] | 0.104 | 0.171 | 0.189 | 100 % | 100 % | 0.103 |
| lego_2x4 | 12 | 0.134 [0.081, 0.192] | 0.079 | 0.286 | 0.299 | 100 % | 100 % | 0.065 |
| sd_card | 12 | 0.057 [0.041, 0.077] | 0.050 | 0.097 | 0.138 | 100 % | 100 % | 0.055 |

| by mat | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| paper-a4 | 5 | 0.230 [0.188, 0.272] | 0.238 | 0.285 | 0.299 | 100 % | 100 % | 0.230 |
| screen-l | 12 | 0.182 [0.077, 0.306] | 0.081 | 0.564 | 0.655 | 83 % | 83 % | -0.091 |
| screen-m | 23 | 0.191 [0.090, 0.315] | 0.066 | 0.590 | 1.161 | 83 % | 87 % | -0.105 |

## reference_objects_real

Ground truth: reference_spec (published spec; real photos).

**pending** — no photos with this ground truth yet.

## real_parts_ruler

Ground truth: ruler (±0.5 mm).

**pending** — no photos with this ground truth yet.

## Failures

| source | sample | view | preset | reason | missed |
|---|---|---|---|---|---|
| reference_objects_synthetic | ref-aa-cell-moire-s66264 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| reference_objects_synthetic | ref-id1-card-moire-s231112 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| reference_objects_synthetic | ref-lego-2x4-moire-s713065 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| reference_objects_synthetic | ref-sd-card-blur-s233099 | top | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-cable-clip-moire-s62281 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-clip-moire-s830875 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-clip-white-part-s468432 | top | white-part | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). | hole_1.diameter |
| synthetic | syn-hinge-leaf-blur-s889433 | top | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-hinge-leaf-moire-s207046 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-hinge-leaf-white-part-s529109 | top | white-part | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). | hole_1.diameter, hole_2.diameter |
| synthetic | syn-hook-tilt-s563265 | top | tilt | capture gate failed: The part touches the markers — move it into the middle of the plain area. |  |
| synthetic | syn-l-bracket-blur-s785210 | top | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-l-bracket-moire-s114398 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-l-bracket-white-part-s103059 | top | white-part | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). | hole_1.diameter, hole_2.diameter, hole_3.diameter |
| synthetic | syn-spacer-moire-s143272 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-spacer-moire-s601695 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-spacer-white-part-s276343 | top | white-part | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). | hole_1.diameter |
| reference_objects_synthetic | ref-lego-2x4-moire-s713065 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| reference_objects_synthetic | ref-sd-card-moire-s61153 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-cable-clip-blur-s254152 | side | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-cable-clip-moire-s62281 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-cable-clip-white-part-s236478 | side | white-part | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). |  |
| synthetic | syn-clip-moire-s830875 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-clip-white-part-s310572 | side | white-part | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). |  |
| synthetic | syn-hinge-leaf-blur-s889433 | side | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-hinge-leaf-moire-s207046 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-l-bracket-blur-s816483 | side | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-l-bracket-moire-s114398 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-l-bracket-moire-s928384 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-l-bracket-white-part-s103059 | side | white-part | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). |  |
| synthetic | syn-spacer-moire-s143272 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-spacer-white-part-s276343 | side | white-part | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). |  |
| synthetic | syn-cable-clip-white-part-s236478 | top | white-part | dimension(s) not measured | hole_1.diameter, hole_2.diameter |
| synthetic | syn-caster-wheel-tilt-s108404 | top | tilt | dimension(s) not measured | hole_1.diameter, hole_2.diameter, hole_3.diameter, hole_5.diameter, hole_6.diameter, hole_7.diameter |
| synthetic | syn-spacer-white-part-s928626 | top | white-part | dimension(s) not measured | hole_1.diameter |

Runtime: 117.6 s. Regenerate: `uv run python -m eval.measure_only`.
