---
id: build
version: 1
model_stage: build
output: one fenced python block
---
# developer
Write a CadQuery program for this PartSpec. Use ONLY `import cadquery as cq` and `import math`, and only the CadQuery
Workplane/Sketch API. Put every dimension in PARAMS as `name: (default, min, max, step, unit, affects_fit, label)`, all in mm.
Define `def build(p: dict) -> cq.Workplane` and end with `result = build({k: v[0] for k, v in PARAMS.items()})`.
Model centred at the origin, +Z up, mounting face on Z = 0, long axis +X.
Prefer the template `{template_name}` when given: copy it and change PARAMS defaults to the PartSpec values instead of writing new
geometry. Include at least one topology parameter (an integer count) when natural. No file IO, no other imports, no names starting
with an underscore. Return one fenced python block and nothing else.
Lessons for family `{family}`:
{lessons}

# user
PartSpec: {partspec}
Template source:
{template_source}
