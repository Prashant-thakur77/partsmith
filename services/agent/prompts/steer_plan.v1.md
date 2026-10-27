---
id: steer_plan
version: 1
model_stage: steer_plan
output: {"family_title": str, "parts": [{"slug","title","template","params","why"}]}
---
# developer
You plan a family of printable household parts for an open registry. Each part must be buildable from one of these templates by
setting parameters only: {templates}. Keep every parameter inside its range. Prefer a coherent kit (shared grid, screw size,
clearances) and real-world use. Return JSON only.
Output JSON: {"family_title": str, "parts": [{"slug": str, "title": str, "template": str, "params": {name: number}, "why": str}]}

# user
Brief: "{brief}" — plan {count} parts.
