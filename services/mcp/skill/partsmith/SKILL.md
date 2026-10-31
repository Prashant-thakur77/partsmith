---
name: partsmith
description: Find, adapt and build 3D-printable replacement parts with the PartSmith MCP tools (search_parts, get_variant, bake, measure_photo, start_fix_job). Use when the user needs a printable functional part — a clip, knob, hook, bracket, spacer, wheel, hinge, latch, cable clip or battery cover — or has photos of a broken plastic part.
---

# PartSmith

PartSmith parts are parametric CadQuery programs with typed knobs (millimetres), a code-decided verification record and
an origin label (`real` = verified against a photo of a real part, `synthetic` = verified against rendered images).

## Workflow
1. **Search first.** `search_parts(q="<object> <size> mm")`. If `match` is `none`, tell the user nothing matched and
   offer `report_need(query=...)`; if it is `partial`, say which words or sizes the best part misses (`coverage` is the
   share it matches, 0–1). Never substitute an unrelated part.
2. **Read the part.** `get_part(slug)` — check the knob ranges, `verification.status` and `max_error_mm`, and `facts`
   (bbox, grams of PLA, supports, orientation).
3. **Adapt with words.** `get_variant(slug, want="M4 hole, 2 mm taller")`. Report `applied` and `not_applied` back to the
   user. Below 0.8 confidence, say exactly what changed.
4. **Bake.** `bake(slug, params=<variant params>, formats=["stl", "step", "3mf"])` → download URLs. Hand over `part.py`
   (`formats=["py"]`) when the user wants to edit the program.
5. **Broken part with photos?** `measure_photo(...)` to check the capture, then `start_fix_job(...)` and poll
   `get_job(job_id)`; the job page URL shows the live run.

## Rules
- Never rescale a part to force a fit — change the knob that matters.
- `bake` refuses best-effort parts until `ack=true`: tell the user the returned reason first, and suggest the fit-test
  coupon. Use `verify(slug, job_id)` to check an existing part against the user's photos before building a new one.
- Units are millimetres. Quote numbers exactly as returned; `best_effort` is not `verified`.
- Say which dimensions were measured, which were stated by the user and which were assumed.
- `start_fix_job` and `report_need` write; everything else is read-only.
