---
id: variant
version: 1
model_stage: variant
output: {"edits": [{"param","to","reason"}], "not_applied": [str], "confidence": number}
---
# developer
A developer or agent asked for a variant of a registry part in plain words. Map the request to parameter values. Only use
parameter names from PARAMS; values must be inside each parameter's range. If part of the request cannot be expressed with the
parameters, list it in `not_applied` — never invent parameters and never rescale the whole part.
Output JSON: {"edits": [{"param": str, "to": number, "reason": str}], "not_applied": [str], "confidence": number}

# user
Request: "{want}"
PARAMS (name, current, min, max, unit, label): {params}
