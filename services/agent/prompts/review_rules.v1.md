---
id: review_rules
version: 1
model_stage: review_rules
output: {"rule": str}
---
# developer
A person reviewed a replacement part that PartSmith rebuilt from photos and left a note. Turn the note into one general rule
for building future parts of the same family, so the same mistake is not made again. The rule must be short (at most 160
characters), start with the family name, say what to check or do, and contain no number that is not in the note or the
evidence. If the note is about this one part only (a one-off, not a lesson for the family), answer "skip".
A person reads every rule before it is used; the rule is advice for the builder, software still decides pass or fail.
Output JSON: {"rule": str}

# user
Family: {family}
Reviewer's note: "{note}"
Where: {where}
Code's local mismatch at the note: {mismatch}
