# measure_only bench — 2026-10-27

Photo → millimetres only: `measure_photo` with the deterministic threshold segmenter (no model, no keys). Errors are |measured − ground truth| in mm. **Accepted** = photos that passed the capture gate (the app asks for a retake otherwise); rejected photos are listed under failures. Sources are never merged.

Synthetic bench: seed 7, n = 60 template samples + 20 reference-object renders, dataset sha256 `a576c6980c08ae02…`. All synthetic.

## Phase 1 exit gate (mean abs error ≤ 0.4 mm, accepted photos)

- synthetic bench: mean 1.503 mm over N = 201 dims → **FAIL**
- reference objects (reference_spec (published spec; synthetic render of the nominal model)): mean 0.346 mm over N = 40 dims → **PASS**
- overall: **FAIL**

## synthetic

Ground truth: synthetic_exact (template mesh, exact).

Photos: 120 (mat + part detected: 120; capture gate passed: 102/120 = 85 % [0.78, 0.90]).

| dims | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| accepted photos | 201 | 1.503 [0.966, 2.140] | 0.174 | 3.357 | 36.253 | 61 % | 71 % | -0.339 |
| all detected photos | 241 | 1.463 [0.963, 2.050] | 0.174 | 3.555 | 36.253 | 60 % | 71 % | -0.125 |

- pass@0.3 mm (every named dim of an accepted photo within 0.3 mm; a missed dim fails): 32/102 = 31 % [0.23, 0.41]
- pass@0.5 mm (every named dim of an accepted photo within 0.5 mm; a missed dim fails): 43/102 = 42 % [0.33, 0.52]

| by dimension | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| hole Ø | 48 | 0.143 [0.111, 0.178] | 0.099 | 0.300 | 0.462 | 90 % | 100 % | -0.116 |
| side:thickness | 51 | 2.451 [1.348, 3.831] | 0.473 | 6.550 | 25.753 | 33 % | 51 % | 0.097 |
| top:length | 51 | 2.006 [0.458, 4.004] | 0.138 | 1.440 | 36.253 | 67 % | 75 % | -1.299 |
| top:width | 51 | 1.333 [0.641, 2.278] | 0.257 | 3.037 | 20.146 | 55 % | 61 % | -0.023 |

| by profile | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| side: flat | 22 | 1.456 [0.283, 3.196] | 0.333 | 1.106 | 13.781 | 45 % | 68 % | 0.890 |
| side: tall features | 29 | 3.205 [1.698, 5.277] | 1.581 | 6.589 | 25.753 | 24 % | 38 % | -0.505 |
| top: flat | 57 | 0.267 [0.169, 0.410] | 0.126 | 0.592 | 3.357 | 77 % | 88 % | -0.055 |
| top: tall features | 93 | 1.741 [0.788, 3.006] | 0.143 | 2.951 | 36.253 | 66 % | 72 % | -0.752 |

| by preset | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| blur | 28 | 0.816 [0.358, 1.328] | 0.211 | 3.399 | 5.315 | 64 % | 75 % | 0.541 |
| clean | 36 | 0.580 [0.299, 0.936] | 0.161 | 1.231 | 4.402 | 67 % | 72 % | 0.430 |
| glare | 32 | 0.468 [0.177, 0.903] | 0.128 | 0.601 | 4.953 | 75 % | 84 % | -0.030 |
| low-light | 31 | 0.448 [0.159, 0.850] | 0.100 | 1.397 | 3.989 | 81 % | 87 % | 0.084 |
| moire | 4 | 0.597 [0.083, 1.353] | 0.276 | 1.375 | 1.771 | 50 % | 75 % | 0.339 |
| paper | 26 | 0.493 [0.250, 0.852] | 0.164 | 1.284 | 3.357 | 62 % | 77 % | 0.220 |
| tilt | 22 | 2.294 [0.894, 4.198] | 0.451 | 6.671 | 13.781 | 45 % | 50 % | 1.902 |
| white-part | 22 | 7.447 [3.414, 12.102] | 1.127 | 25.192 | 36.253 | 14 % | 36 % | -6.784 |

| by family / object | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| bracket | 16 | 3.783 [1.100, 7.314] | 1.289 | 10.280 | 25.753 | 38 % | 44 % | -1.686 |
| cable_clip | 22 | 2.375 [0.323, 5.676] | 0.182 | 6.026 | 29.574 | 59 % | 73 % | -2.023 |
| clip | 19 | 1.463 [0.555, 2.714] | 0.332 | 3.373 | 10.369 | 42 % | 58 % | 0.290 |
| cover | 18 | 1.126 [0.423, 1.951] | 0.097 | 3.226 | 6.742 | 67 % | 67 % | 0.383 |
| hinge | 20 | 3.258 [0.254, 7.788] | 0.247 | 5.976 | 36.253 | 60 % | 70 % | -2.505 |
| hook | 23 | 1.238 [0.524, 2.032] | 0.196 | 4.760 | 6.029 | 57 % | 61 % | 1.074 |
| knob | 18 | 0.964 [0.123, 2.270] | 0.166 | 1.228 | 11.687 | 83 % | 89 % | 0.740 |
| latch | 21 | 0.208 [0.118, 0.312] | 0.110 | 0.473 | 0.988 | 76 % | 90 % | -0.077 |
| spacer | 13 | 0.324 [0.146, 0.533] | 0.138 | 0.865 | 1.153 | 62 % | 77 % | -0.091 |
| wheel | 31 | 0.701 [0.210, 1.611] | 0.136 | 0.599 | 13.781 | 61 % | 77 % | 0.191 |

| by mat | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| paper-a4 | 46 | 1.702 [0.693, 3.179] | 0.309 | 3.880 | 29.574 | 50 % | 65 % | -0.598 |
| screen-l | 61 | 1.920 [0.745, 3.532] | 0.112 | 4.953 | 36.253 | 66 % | 75 % | -0.453 |
| screen-m | 94 | 1.135 [0.566, 1.903] | 0.155 | 2.814 | 25.753 | 63 % | 71 % | -0.137 |

## reference_objects_synthetic

Ground truth: reference_spec (published spec; synthetic render of the nominal model).

Photos: 30 (mat + part detected: 30; capture gate passed: 24/30 = 80 % [0.63, 0.90]).

| dims | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| accepted photos | 40 | 0.346 [0.146, 0.685] | 0.095 | 0.646 | 6.037 | 80 % | 85 % | 0.095 |
| all detected photos | 50 | 0.426 [0.159, 0.798] | 0.085 | 0.646 | 6.400 | 80 % | 86 % | 0.198 |

- pass@0.3 mm (every named dim of an accepted photo within 0.3 mm; a missed dim fails): 18/24 = 75 % [0.55, 0.88]
- pass@0.5 mm (every named dim of an accepted photo within 0.5 mm; a missed dim fails): 19/24 = 79 % [0.60, 0.91]
- inside the spec's accepted range: 24/40 = 60 % [0.45, 0.74]

| by dimension | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| side:thickness | 8 | 0.881 [0.095, 2.370] | 0.119 | 2.020 | 6.037 | 88 % | 88 % | 0.778 |
| top:length | 16 | 0.267 [0.116, 0.447] | 0.071 | 0.710 | 1.161 | 69 % | 75 % | -0.130 |
| top:width | 16 | 0.158 [0.088, 0.244] | 0.087 | 0.320 | 0.655 | 88 % | 94 % | -0.023 |

| by preset | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| blur | 8 | 0.310 [0.184, 0.456] | 0.285 | 0.612 | 0.655 | 62 % | 75 % | -0.003 |
| clean | 10 | 0.185 [0.098, 0.305] | 0.151 | 0.325 | 0.645 | 90 % | 90 % | -0.048 |
| glare | 10 | 0.133 [0.041, 0.284] | 0.053 | 0.248 | 0.775 | 90 % | 90 % | -0.065 |
| moire | 2 | 0.066 [0.065, 0.067] | 0.066 | 0.067 | 0.067 | 100 % | 100 % | 0.066 |
| tilt | 10 | 0.806 [0.078, 2.057] | 0.087 | 1.649 | 6.037 | 70 % | 80 % | 0.480 |

| by family / object | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| aa_cell | 8 | 0.578 [0.381, 0.795] | 0.619 | 0.891 | 1.161 | 25 % | 38 % | -0.578 |
| id1_card | 8 | 0.103 [0.068, 0.141] | 0.104 | 0.171 | 0.189 | 100 % | 100 % | 0.103 |
| lego_2x4 | 12 | 0.141 [0.082, 0.204] | 0.079 | 0.298 | 0.312 | 92 % | 100 % | 0.072 |
| sd_card | 12 | 0.559 [0.050, 1.559] | 0.056 | 0.134 | 6.037 | 92 % | 92 % | 0.559 |

| by mat | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| paper-a4 | 5 | 0.247 [0.195, 0.299] | 0.271 | 0.307 | 0.312 | 80 % | 100 % | 0.247 |
| screen-l | 12 | 0.182 [0.077, 0.306] | 0.081 | 0.564 | 0.655 | 83 % | 83 % | -0.091 |
| screen-m | 23 | 0.453 [0.117, 1.018] | 0.068 | 0.749 | 6.037 | 78 % | 83 % | 0.158 |

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
| synthetic | syn-hinge-leaf-blur-s889433 | top | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-hinge-leaf-moire-s207046 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-hook-tilt-s563265 | top | tilt | capture gate failed: The part touches the markers — move it into the middle of the plain area. | hole_1.diameter, hole_2.diameter |
| synthetic | syn-l-bracket-blur-s785210 | top | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-l-bracket-moire-s114398 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-spacer-moire-s143272 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. | hole_1.diameter |
| synthetic | syn-spacer-moire-s601695 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. | hole_1.diameter |
| reference_objects_synthetic | ref-lego-2x4-moire-s713065 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| reference_objects_synthetic | ref-sd-card-moire-s61153 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-cable-clip-blur-s254152 | side | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-cable-clip-moire-s62281 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-clip-moire-s830875 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-hinge-leaf-blur-s889433 | side | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-hinge-leaf-moire-s207046 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-l-bracket-blur-s816483 | side | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-l-bracket-moire-s114398 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-l-bracket-moire-s928384 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-spacer-moire-s143272 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-cable-clip-white-part-s236478 | top | white-part | dimension(s) not measured | hole_1.diameter, hole_2.diameter |
| synthetic | syn-caster-wheel-glare-s452643 | top | glare | dimension(s) not measured | hole_1.diameter, hole_2.diameter |
| synthetic | syn-caster-wheel-paper-s594413 | top | paper | dimension(s) not measured | hole_1.diameter, hole_2.diameter, hole_3.diameter, hole_4.diameter, hole_5.diameter, hole_6.diameter |
| synthetic | syn-caster-wheel-paper-s721064 | top | paper | dimension(s) not measured | hole_1.diameter, hole_2.diameter, hole_5.diameter, hole_6.diameter, hole_7.diameter |
| synthetic | syn-caster-wheel-tilt-s108404 | top | tilt | dimension(s) not measured | hole_1.diameter, hole_2.diameter, hole_3.diameter, hole_4.diameter, hole_5.diameter, hole_6.diameter, hole_7.diameter |
| synthetic | syn-caster-wheel-tilt-s847482 | top | tilt | dimension(s) not measured | hole_1.diameter, hole_2.diameter, hole_3.diameter, hole_4.diameter, hole_5.diameter, hole_6.diameter |
| synthetic | syn-clip-white-part-s468432 | top | white-part | dimension(s) not measured | hole_1.diameter |
| synthetic | syn-cupboard-latch-paper-s572177 | top | paper | dimension(s) not measured | hole_1.diameter |
| synthetic | syn-cupboard-latch-tilt-s499291 | top | tilt | dimension(s) not measured | hole_1.diameter |
| synthetic | syn-cupboard-latch-tilt-s522860 | top | tilt | dimension(s) not measured | hole_1.diameter |
| synthetic | syn-hinge-leaf-white-part-s529109 | top | white-part | dimension(s) not measured | hole_1.diameter, hole_2.diameter |
| synthetic | syn-hook-glare-s409132 | top | glare | dimension(s) not measured | hole_1.diameter |
| synthetic | syn-hook-tilt-s656341 | top | tilt | dimension(s) not measured | hole_1.diameter |
| synthetic | syn-l-bracket-white-part-s103059 | top | white-part | dimension(s) not measured | hole_1.diameter, hole_2.diameter, hole_3.diameter |
| synthetic | syn-spacer-blur-s21267 | top | blur | dimension(s) not measured | hole_1.diameter |
| synthetic | syn-spacer-clean-s318180 | top | clean | dimension(s) not measured | hole_1.diameter |
| synthetic | syn-spacer-white-part-s276343 | top | white-part | dimension(s) not measured | hole_1.diameter |
| synthetic | syn-spacer-white-part-s928626 | top | white-part | dimension(s) not measured | hole_1.diameter |

Runtime: 234.0 s. Regenerate: `uv run python -m eval.measure_only`.
