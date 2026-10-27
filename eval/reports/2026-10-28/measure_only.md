# measure_only bench — 2026-10-28

Photo → millimetres only: `measure_photo` with the deterministic threshold segmenter (no model, no keys). Errors are |measured − ground truth| in mm. **Accepted** = photos that passed the capture gate (the app asks for a retake otherwise); rejected photos are listed under failures. Sources are never merged.

Synthetic bench: seed 7, n = 60 template samples + 20 reference-object renders, dataset sha256 `f0125ffd9022d77a…`. All synthetic.

## Phase 1 exit gate (mean abs error ≤ 0.4 mm, accepted photos)

- synthetic bench: mean 0.468 mm over N = 228 dims → **FAIL**
- reference objects (reference_spec (published spec; synthetic render of the nominal model)): mean 0.178 mm over N = 35 dims → **PASS**
- overall: **FAIL**

## synthetic

Ground truth: synthetic_exact (template mesh, exact).

Photos: 120 (mat + part detected: 120; capture gate passed: 97/120 = 81 % [0.73, 0.87]).

| dims | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| accepted photos | 228 | 0.468 [0.370, 0.580] | 0.200 | 1.039 | 5.316 | 68 % | 77 % | -0.044 |
| all detected photos | 279 | 0.549 [0.418, 0.709] | 0.197 | 1.097 | 14.799 | 66 % | 76 % | 0.076 |

- pass@0.3 mm (every named dim of an accepted photo within 0.3 mm; a missed dim fails): 37/97 = 38 % [0.29, 0.48]
- pass@0.5 mm (every named dim of an accepted photo within 0.5 mm; a missed dim fails): 51/97 = 53 % [0.43, 0.62]
- expected rejections (white part on the light stage → dark-stage retake): 5/6 correctly rejected [0.44, 0.97]; not scored as errors; missed: syn-spacer-white-on-light-s706141

| top view (accepted photos) | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| top view, flat parts | 82 | 0.226 [0.181, 0.273] | 0.165 | 0.544 | 0.936 | 79 % | 89 % | -0.153 |
| top view, parts with tall features | 98 | 0.494 [0.324, 0.690] | 0.129 | 1.378 | 5.316 | 73 % | 79 % | 0.412 |

A single top photo sees only the silhouette, and the height correction assumes every outline edge sits at the stated thickness, so features that stand taller than that (arms, uprights, knuckles) are displaced by parallax by an amount the photo cannot resolve; the full-loop bench scores the final model instead.

| by dimension | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| hole Ø | 82 | 0.165 [0.133, 0.199] | 0.093 | 0.287 | 0.802 | 90 % | 98 % | -0.055 |
| side:thickness | 48 | 0.828 [0.559, 1.133] | 0.490 | 2.678 | 3.622 | 38 % | 52 % | -0.789 |
| top:length | 49 | 0.474 [0.261, 0.760] | 0.136 | 1.024 | 5.316 | 71 % | 76 % | 0.248 |
| top:width | 49 | 0.617 [0.382, 0.894] | 0.231 | 1.745 | 3.928 | 57 % | 67 % | 0.413 |

| by profile | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| side: flat | 20 | 0.363 [0.245, 0.498] | 0.271 | 0.759 | 1.086 | 50 % | 70 % | -0.275 |
| side: tall features | 28 | 1.161 [0.769, 1.605] | 0.729 | 3.120 | 3.622 | 29 % | 39 % | -1.156 |
| top: flat | 82 | 0.226 [0.181, 0.273] | 0.165 | 0.544 | 0.936 | 79 % | 89 % | -0.153 |
| top: tall features | 98 | 0.494 [0.324, 0.690] | 0.129 | 1.378 | 5.316 | 73 % | 79 % | 0.412 |

| by preset | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| blur | 29 | 0.703 [0.280, 1.222] | 0.210 | 1.834 | 5.316 | 66 % | 76 % | 0.387 |
| clean | 37 | 0.379 [0.225, 0.578] | 0.132 | 0.961 | 3.036 | 70 % | 78 % | 0.213 |
| glare | 27 | 0.345 [0.142, 0.655] | 0.106 | 0.584 | 3.622 | 78 % | 85 % | -0.190 |
| low-light | 31 | 0.323 [0.138, 0.579] | 0.097 | 1.081 | 3.056 | 77 % | 87 % | -0.182 |
| moire | 4 | 0.491 [0.067, 1.321] | 0.086 | 1.243 | 1.735 | 75 % | 75 % | 0.463 |
| paper | 38 | 0.364 [0.226, 0.553] | 0.265 | 0.479 | 2.516 | 76 % | 89 % | -0.275 |
| tilt | 32 | 0.527 [0.272, 0.844] | 0.194 | 0.966 | 3.237 | 62 % | 69 % | -0.279 |
| white-part | 30 | 0.680 [0.416, 1.021] | 0.496 | 1.156 | 3.611 | 43 % | 50 % | -0.026 |

| by family / object | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| bracket | 19 | 1.227 [0.598, 1.964] | 0.408 | 3.674 | 5.316 | 47 % | 53 % | 0.869 |
| cable_clip | 24 | 0.267 [0.150, 0.401] | 0.172 | 0.634 | 1.311 | 75 % | 88 % | 0.091 |
| clip | 20 | 0.584 [0.292, 0.992] | 0.209 | 1.098 | 3.588 | 55 % | 60 % | 0.298 |
| cover | 18 | 0.931 [0.384, 1.543] | 0.099 | 3.060 | 3.622 | 67 % | 67 % | -0.822 |
| hinge | 20 | 0.419 [0.179, 0.769] | 0.215 | 0.847 | 3.335 | 65 % | 80 % | -0.095 |
| hook | 21 | 0.665 [0.333, 1.069] | 0.196 | 1.382 | 3.237 | 62 % | 62 % | 0.004 |
| knob | 14 | 0.206 [0.153, 0.253] | 0.230 | 0.318 | 0.354 | 86 % | 100 % | -0.142 |
| latch | 24 | 0.200 [0.135, 0.265] | 0.144 | 0.404 | 0.639 | 71 % | 96 % | -0.079 |
| spacer | 17 | 0.411 [0.243, 0.595] | 0.208 | 0.913 | 1.086 | 59 % | 59 % | -0.153 |
| wheel | 51 | 0.228 [0.175, 0.289] | 0.179 | 0.571 | 0.853 | 78 % | 86 % | -0.226 |

| by mat | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| paper-a4 | 53 | 0.426 [0.294, 0.596] | 0.266 | 0.831 | 2.613 | 70 % | 85 % | -0.146 |
| screen-l | 61 | 0.533 [0.334, 0.759] | 0.128 | 1.376 | 3.588 | 66 % | 70 % | -0.093 |
| screen-m | 114 | 0.453 [0.304, 0.621] | 0.128 | 0.991 | 5.316 | 68 % | 76 % | 0.031 |

## reference_objects_synthetic

Ground truth: reference_spec (published spec; synthetic render of the nominal model).

Photos: 30 (mat + part detected: 30; capture gate passed: 21/30 = 70 % [0.52, 0.83]).

| dims | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| accepted photos | 35 | 0.178 [0.114, 0.264] | 0.087 | 0.307 | 1.312 | 89 % | 91 % | 0.015 |
| all detected photos | 50 | 0.158 [0.105, 0.227] | 0.076 | 0.298 | 1.312 | 90 % | 92 % | 0.004 |

- pass@0.3 mm (every named dim of an accepted photo within 0.3 mm; a missed dim fails): 17/21 = 81 % [0.60, 0.92]
- pass@0.5 mm (every named dim of an accepted photo within 0.5 mm; a missed dim fails): 18/21 = 86 % [0.65, 0.95]
- inside the spec's accepted range: 15/35 = 43 % [0.28, 0.59]

| by dimension | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| side:thickness | 7 | 0.152 [0.079, 0.225] | 0.141 | 0.291 | 0.296 | 100 % | 100 % | 0.041 |
| top:length | 14 | 0.261 [0.112, 0.458] | 0.080 | 0.576 | 1.312 | 71 % | 79 % | -0.090 |
| top:width | 14 | 0.107 [0.075, 0.143] | 0.081 | 0.214 | 0.272 | 100 % | 100 % | 0.107 |

| by preset | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| blur | 8 | 0.279 [0.207, 0.377] | 0.254 | 0.395 | 0.583 | 75 % | 88 % | 0.133 |
| clean | 10 | 0.164 [0.086, 0.270] | 0.115 | 0.314 | 0.559 | 90 % | 90 % | -0.005 |
| glare | 5 | 0.057 [0.048, 0.067] | 0.060 | 0.070 | 0.072 | 100 % | 100 % | 0.057 |
| moire | 2 | 0.077 [0.076, 0.078] | 0.077 | 0.078 | 0.078 | 100 % | 100 % | 0.077 |
| tilt | 10 | 0.191 [0.051, 0.448] | 0.079 | 0.220 | 1.312 | 90 % | 90 % | -0.091 |

| by family / object | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| aa_cell | 6 | 0.476 [0.185, 0.857] | 0.398 | 0.948 | 1.312 | 50 % | 50 % | -0.342 |
| id1_card | 6 | 0.147 [0.109, 0.182] | 0.159 | 0.199 | 0.207 | 100 % | 100 % | 0.147 |
| lego_2x4 | 11 | 0.153 [0.093, 0.217] | 0.097 | 0.296 | 0.314 | 91 % | 100 % | 0.083 |
| sd_card | 12 | 0.066 [0.045, 0.094] | 0.049 | 0.135 | 0.170 | 100 % | 100 % | 0.066 |

| by mat | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| paper-a4 | 5 | 0.247 [0.196, 0.298] | 0.272 | 0.307 | 0.314 | 80 % | 100 % | 0.247 |
| screen-l | 12 | 0.150 [0.082, 0.245] | 0.084 | 0.282 | 0.583 | 92 % | 92 % | -0.011 |
| screen-m | 18 | 0.176 [0.071, 0.332] | 0.070 | 0.313 | 1.312 | 89 % | 89 % | -0.031 |

## reference_objects_real

Ground truth: reference_spec (published spec; real photos).

**pending** — no photos with this ground truth yet.

## real_parts_ruler

Ground truth: ruler (±0.5 mm).

**pending** — no photos with this ground truth yet.

## Failures

| source | sample | view | preset | reason | missed |
|---|---|---|---|---|---|
| reference_objects_synthetic | ref-aa-cell-glare-s425689 | top | glare | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). |  |
| reference_objects_synthetic | ref-aa-cell-moire-s66264 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| reference_objects_synthetic | ref-id1-card-glare-s759563 | top | glare | capture gate failed: Two separate objects are on the mat — photograph one part at a time. |  |
| reference_objects_synthetic | ref-id1-card-moire-s231112 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| reference_objects_synthetic | ref-lego-2x4-moire-s713065 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| reference_objects_synthetic | ref-sd-card-blur-s233099 | top | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-cable-clip-moire-s62281 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-clip-moire-s830875 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-hinge-leaf-blur-s889433 | top | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-hinge-leaf-moire-s207046 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-hook-glare-s409132 | top | glare | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). |  |
| synthetic | syn-hook-tilt-s563265 | top | tilt | capture gate failed: The part touches the markers — move it into the middle of the plain area. |  |
| synthetic | syn-knob-glare-s198000 | top | glare | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). |  |
| synthetic | syn-l-bracket-blur-s785210 | top | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-l-bracket-moire-s114398 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-spacer-moire-s143272 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-spacer-moire-s601695 | top | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. | hole_1.diameter |
| reference_objects_synthetic | ref-lego-2x4-glare-s431248 | side | glare | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). |  |
| reference_objects_synthetic | ref-lego-2x4-moire-s713065 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| reference_objects_synthetic | ref-sd-card-moire-s61153 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-cable-clip-blur-s254152 | side | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-cable-clip-moire-s62281 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-clip-moire-s830875 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-hinge-leaf-blur-s889433 | side | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-hinge-leaf-moire-s207046 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-hook-glare-s235877 | side | glare | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). |  |
| synthetic | syn-knob-glare-s198000 | side | glare | capture gate failed: Two separate objects are on the mat — photograph one part at a time. |  |
| synthetic | syn-knob-glare-s390629 | side | glare | capture gate failed: The part blends into the background — switch the screen mat to the dark stage (or use a darker surface). |  |
| synthetic | syn-l-bracket-blur-s816483 | side | blur | capture gate failed: The photo is blurry — hold the phone still, tap to focus on the part and retake. |  |
| synthetic | syn-l-bracket-moire-s114398 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-l-bracket-moire-s928384 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-spacer-moire-s143272 | side | moire | capture gate failed: Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly. |  |
| synthetic | syn-spacer-white-on-light-s706141 | top | white-on-light | missed rejection: the capture gate accepted a white part on the light stage |  |
| synthetic | syn-caster-wheel-tilt-s108404 | top | tilt | dimension(s) not measured | hole_1.diameter, hole_2.diameter, hole_3.diameter, hole_5.diameter, hole_6.diameter, hole_7.diameter |
| synthetic | syn-hinge-leaf-white-part-s529109 | top | white-part | dimension(s) not measured | hole_1.diameter, hole_2.diameter |

Runtime: 277.1 s. Regenerate: `uv run python -m eval.measure_only`.
