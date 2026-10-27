---
id: voice_edit
version: 1
model_stage: voice_map
output: {"edits": [{"param","to","reason"}], "not_understood": [str], "confidence": number}
---
# developer
Map the user's spoken request (it may mix Hindi and English) to parameter edits for this part. Only use parameter names from
PARAMS. Relative words ("thoda", "a bit", "slightly") mean 0.2 mm for holes and clearances and 0.5 mm otherwise, unless the
user gives a number. "mota/thick" = thickness up, "patla/thin" = down, "bada/bigger" = up, "chhota/smaller" = down.
Output JSON: {"edits": [{"param": str, "to": number, "reason": str}], "not_understood": [str], "confidence": number between 0 and 1}

# user
Transcript: "{transcript}"
PARAMS with current values: {params}
