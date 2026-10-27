---
id: fix
version: 1
model_stage: fix
output: {"analysis": str, "edits": [{"param","from","to","reason"}]} or {"analysis": str, "code_patch": str}
---
# developer
The verifier measured your model against the photo. The residuals are computed by code and are correct.
Fix exactly the largest residuals first; keep everything that already matches. Prefer parameter edits over code edits.
Never rescale the whole outline to force a fit — change the right knob. Max change per parameter this round: {limits}.
Only use parameter names from PARAMS: {param_names}.
Return JSON: {"analysis": str, "edits": [{"param": str, "from": number, "to": number, "reason": str}]}
or {"analysis": str, "code_patch": "<full replacement program>"} when no parameter can fix the residual.

# user
Residual table (sorted by |delta|, mm): {residuals}
View metrics: {views}
Current PARAMS values: {values}
Last edits and their measured effect: {history}
Overlay image attached (orange = model has extra material, blue = model is missing material).
