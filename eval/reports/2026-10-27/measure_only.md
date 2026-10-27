# measure_only bench — 2026-10-27

Photo → millimetres only: `measure_photo` with the deterministic threshold segmenter (no model, no keys). Errors are |measured − ground truth| in mm. **Accepted** = photos that passed the capture gate (the app asks for a retake otherwise); rejected photos are listed under failures. Sources are never merged.

Synthetic bench: seed 7, n = 60 template samples + 20 reference-object renders, dataset sha256 `f0125ffd9022d77a…`. All synthetic.

## Phase 1 exit gate (mean abs error ≤ 0.4 mm, accepted photos)

- synthetic bench: mean 0.667 mm over N = 228 dims → **FAIL**
- reference objects (reference_spec (published spec; synthetic render of the nominal model)): mean 0.170 mm over N = 40 dims → **PASS**
- overall: **FAIL**

## synthetic

Ground truth: synthetic_exact (template mesh, exact).

Photos: 120 (mat + part detected: 120; capture gate passed: 100/120 = 83 % [0.76, 0.89]).

| dims | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| accepted photos | 228 | 0.667 [0.437, 0.968] | 0.164 | 1.350 | 24.170 | 67 % | 76 % | -0.261 |
| all detected photos | 278 | 0.806 [0.540, 1.146] | 0.168 | 1.397 | 24.170 | 65 % | 75 % | -0.229 |

- pass@0.3 mm (every named dim of an accepted photo within 0.3 mm; a missed dim fails): 39/100 = 39 % [0.30, 0.49]
- pass@0.5 mm (every named dim of an accepted photo within 0.5 mm; a missed dim fails): 53/100 = 53 % [0.43, 0.62]
- expected rejections (white part on the light stage → dark-stage retake): 4/6 correctly rejected [0.30, 0.90]; not scored as errors; missed: syn-hinge-leaf-white-on-light-s939262, syn-spacer-white-on-light-s706141

| top view (accepted photos) | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| top view, flat parts | 83 | 0.223 [0.174, 0.282] | 0.150 | 0.459 | 1.342 | 77 % | 90 % | -0.162 |
| top view, parts with tall features | 94 | 0.811 [0.399, 1.411] | 0.134 | 1.427 | 24.170 | 73 % | 77 % | 0.100 |

A single top photo sees only the silhouette, and the height correction assumes every outline edge sits at the stated thickness, so features that stand taller than that (arms, uprights, knuckles) are displaced by parallax by an amount the photo cannot resolve; the full-loop bench scores the final model instead.

| by dimension | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| hole Ø | 79 | 0.149 [0.119, 0.188] | 0.096 | 0.301 | 1.216 | 90 % | 99 % | -0.043 |
| side:thickness | 51 | 1.122 [0.628, 1.872] | 0.424 | 2.749 | 16.297 | 39 % | 53 % | -1.087 |
| top:length | 49 | 0.900 [0.258, 1.958] | 0.138 | 1.347 | 24.170 | 71 % | 76 % | -0.353 |
| top:width | 49 | 0.793 [0.484, 1.166] | 0.263 | 2.693 | 5.049 | 55 % | 65 % | 0.340 |

| by profile | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| side: flat | 22 | 0.376 [0.226, 0.565] | 0.249 | 0.832 | 1.900 | 55 % | 73 % | -0.299 |
| side: tall features | 29 | 1.688 [0.887, 2.935] | 0.691 | 3.105 | 16.297 | 28 % | 38 % | -1.685 |
| top: flat | 83 | 0.223 [0.174, 0.282] | 0.150 | 0.459 | 1.342 | 77 % | 90 % | -0.162 |
| top: tall features | 94 | 0.811 [0.399, 1.411] | 0.134 | 1.427 | 24.170 | 73 % | 77 % | 0.100 |

| by preset | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| blur | 29 | 0.684 [0.261, 1.203] | 0.172 | 1.835 | 5.315 | 72 % | 76 % | 0.395 |
| clean | 37 | 0.372 [0.218, 0.571] | 0.136 | 0.960 | 3.037 | 70 % | 76 % | 0.216 |
| glare | 35 | 0.440 [0.162, 0.806] | 0.112 | 0.590 | 4.953 | 74 % | 86 % | -0.010 |
| low-light | 31 | 0.310 [0.124, 0.571] | 0.086 | 1.098 | 3.055 | 81 % | 87 % | -0.177 |
| moire | 4 | 0.507 [0.073, 1.352] | 0.098 | 1.270 | 1.771 | 75 % | 75 % | 0.476 |
| paper | 38 | 0.362 [0.215, 0.564] | 0.180 | 0.452 | 2.749 | 68 % | 89 % | -0.279 |
| tilt | 32 | 0.526 [0.270, 0.848] | 0.178 | 1.055 | 3.251 | 62 % | 69 % | -0.280 |
| white-part | 22 | 2.761 [0.813, 5.428] | 0.793 | 4.814 | 24.170 | 27 % | 36 % | -2.523 |

| by family / object | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| bracket | 19 | 1.908 [0.643, 3.745] | 0.374 | 4.204 | 16.297 | 47 % | 58 % | -0.204 |
| cable_clip | 20 | 0.275 [0.141, 0.433] | 0.149 | 0.748 | 1.282 | 80 % | 85 % | 0.104 |
| clip | 17 | 0.578 [0.248, 1.029] | 0.200 | 1.205 | 3.587 | 59 % | 59 % | 0.192 |
| cover | 18 | 0.937 [0.377, 1.578] | 0.084 | 3.059 | 3.630 | 67 % | 67 % | -0.849 |
| hinge | 20 | 1.812 [0.271, 4.441] | 0.166 | 2.929 | 24.170 | 60 % | 65 % | -1.532 |
| hook | 25 | 0.799 [0.394, 1.294] | 0.177 | 2.123 | 4.953 | 56 % | 64 % | 0.197 |
| knob | 18 | 0.170 [0.123, 0.217] | 0.166 | 0.291 | 0.316 | 94 % | 100 % | -0.121 |
| latch | 24 | 0.199 [0.135, 0.265] | 0.138 | 0.407 | 0.647 | 71 % | 96 % | -0.083 |
| spacer | 16 | 0.533 [0.268, 0.823] | 0.164 | 1.293 | 1.900 | 56 % | 62 % | -0.311 |
| wheel | 51 | 0.214 [0.162, 0.277] | 0.153 | 0.568 | 0.853 | 73 % | 86 % | -0.212 |

| by mat | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| paper-a4 | 53 | 0.415 [0.278, 0.595] | 0.221 | 0.833 | 2.749 | 68 % | 83 % | -0.146 |
| screen-l | 64 | 1.024 [0.442, 1.981] | 0.129 | 2.455 | 24.170 | 64 % | 70 % | -0.529 |
| screen-m | 111 | 0.581 [0.328, 0.939] | 0.127 | 1.098 | 16.297 | 68 % | 77 % | -0.161 |

## reference_objects_synthetic

Ground truth: reference_spec (published spec; synthetic render of the nominal model).

Photos: 30 (mat + part detected: 30; capture gate passed: 24/30 = 80 % [0.63, 0.90]).

| dims | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| accepted photos | 40 | 0.170 [0.106, 0.250] | 0.081 | 0.329 | 1.161 | 90 % | 90 % | -0.010 |
| all detected photos | 50 | 0.153 [0.100, 0.219] | 0.070 | 0.307 | 1.161 | 90 % | 92 % | -0.006 |

- pass@0.3 mm (every named dim of an accepted photo within 0.3 mm; a missed dim fails): 20/24 = 83 % [0.64, 0.93]
- pass@0.5 mm (every named dim of an accepted photo within 0.5 mm; a missed dim fails): 20/24 = 83 % [0.64, 0.93]
- inside the spec's accepted range: 21/40 = 52 % [0.37, 0.67]

| by dimension | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| side:thickness | 8 | 0.120 [0.062, 0.188] | 0.100 | 0.253 | 0.289 | 100 % | 100 % | 0.014 |
| top:length | 16 | 0.266 [0.116, 0.447] | 0.071 | 0.710 | 1.161 | 75 % | 75 % | -0.130 |
| top:width | 16 | 0.098 [0.069, 0.130] | 0.081 | 0.196 | 0.263 | 100 % | 100 % | 0.098 |

| by preset | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| blur | 8 | 0.246 [0.159, 0.363] | 0.233 | 0.387 | 0.594 | 88 % | 88 % | 0.098 |
| clean | 10 | 0.171 [0.083, 0.295] | 0.113 | 0.325 | 0.645 | 90 % | 90 % | -0.016 |
| glare | 10 | 0.124 [0.040, 0.273] | 0.053 | 0.169 | 0.775 | 90 % | 90 % | -0.036 |
| moire | 2 | 0.066 [0.065, 0.067] | 0.066 | 0.067 | 0.067 | 100 % | 100 % | 0.066 |
| tilt | 10 | 0.174 [0.051, 0.401] | 0.076 | 0.206 | 1.161 | 90 % | 90 % | -0.080 |

| by family / object | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| aa_cell | 8 | 0.459 [0.208, 0.719] | 0.411 | 0.891 | 1.161 | 50 % | 50 % | -0.335 |
| id1_card | 8 | 0.103 [0.068, 0.141] | 0.104 | 0.171 | 0.189 | 100 % | 100 % | 0.103 |
| lego_2x4 | 12 | 0.134 [0.081, 0.192] | 0.079 | 0.286 | 0.299 | 100 % | 100 % | 0.065 |
| sd_card | 12 | 0.057 [0.041, 0.077] | 0.050 | 0.097 | 0.138 | 100 % | 100 % | 0.055 |

| by mat | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| paper-a4 | 5 | 0.230 [0.188, 0.272] | 0.238 | 0.285 | 0.299 | 100 % | 100 % | 0.230 |
| screen-l | 12 | 0.147 [0.077, 0.244] | 0.081 | 0.283 | 0.594 | 92 % | 92 % | -0.017 |
| screen-m | 23 | 0.168 [0.068, 0.293] | 0.066 | 0.544 | 1.161 | 87 % | 87 % | -0.059 |

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
| synthetic | syn-cable-clip-white-part-s236478 | top | white-part | capture gate failed: The part blends into the background — switch the screen mat to the light stage (or use a lighter surface). | hole_2.diameter |
| synthetic | syn-clip-moire-s830875 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-clip-white-part-s310572 | top | white-part | capture gate failed: The part blends into the background — switch the screen mat to the light stage (or use a lighter surface). |  |
| synthetic | syn-hinge-leaf-blur-s889433 | top | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-hinge-leaf-moire-s207046 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-hook-tilt-s563265 | top | tilt | capture gate failed: The part touches the markers — move it into the middle of the plain area. |  |
| synthetic | syn-l-bracket-blur-s785210 | top | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-l-bracket-moire-s114398 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-spacer-moire-s143272 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-spacer-moire-s601695 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
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
| synthetic | syn-hinge-leaf-white-on-light-s939262 | top | white-on-light | missed rejection: the capture gate accepted a white part on the light stage |  |
| synthetic | syn-spacer-white-on-light-s706141 | top | white-on-light | missed rejection: the capture gate accepted a white part on the light stage |  |
| synthetic | syn-caster-wheel-tilt-s108404 | top | tilt | dimension(s) not measured | hole_1.diameter, hole_2.diameter, hole_3.diameter, hole_5.diameter, hole_6.diameter, hole_7.diameter |
| synthetic | syn-hinge-leaf-white-part-s529109 | top | white-part | dimension(s) not measured | hole_1.diameter, hole_2.diameter |
| synthetic | syn-spacer-white-part-s276343 | top | white-part | dimension(s) not measured | hole_1.diameter |

Runtime: 438.3 s. Regenerate: `uv run python -m eval.measure_only`.
