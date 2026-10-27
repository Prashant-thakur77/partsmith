/** Part families (mirrors `partsmith_schemas.partspec.Family`). */
export const FAMILIES = [
  "clip",
  "knob",
  "bracket",
  "hook",
  "spacer",
  "cover",
  "wheel",
  "latch",
  "gear",
  "cable_clip",
  "hinge",
  "custom",
] as const;
export type FamilyName = (typeof FAMILIES)[number];
