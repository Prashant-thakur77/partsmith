/**
 * Plain sentences that explain a verdict next to numbers that look like they disagree: which checks passed and which
 * one decided a best-effort status, a verified result sitting right at the limit, a model box that is not the photo's
 * length, a thickness the user stated next to a different photo measurement, and install-card steps written for
 * moving parts. Every number is copied from the verification record or the job's own data; nothing here changes a
 * verdict. Pure and free of runtime imports so `node --test` can load it directly.
 */

type View = { view: string; iou: number; hausdorff_mm: number; mean_mm?: number | null };
type Test = { id: string; description: string; value: number | null; expected: number | null; tol: number | null; passed: boolean; priority?: "P0" | "P1" };
type Residual = { feature_id: string; quantity: string; measured_mm: number; model_mm: number; tol_mm: number; passed: boolean };

export type VerdictRecord = {
  verified: boolean;
  status: string;
  reasons: readonly string[];
  thresholds: { hausdorff_mm: number; iou: number };
  views: readonly View[];
  tests: readonly Test[];
  vetoes?: readonly { feature: string; issue: string; severity: string }[];
  residuals?: readonly Residual[];
  validity?: { bbox_mm: readonly [number, number, number] } | null;
  max_error_mm?: number | null;
};

const f2 = (v: number) => v.toFixed(2);

// ── which checks passed, which failed, which decided ─────────────────────────────────────────────────────────────────

export type VerdictBreakdown = { passed: string[]; failed: string[]; notGated: string[]; decided: string };

type ViewCheck = { ok: boolean; passed: string[]; failed: string[]; notGated: string | null };

/** One view, from the verifier's own line for it ("side view (photo frame): IoU … - fails") when there is one, else
 * from the view's numbers against the two thresholds every view is held to. */
function checkView(v: View, reasons: readonly string[], t: VerdictRecord["thresholds"]): ViewCheck {
  const line = reasons.find((r) => r.toLowerCase().startsWith(`${v.view.toLowerCase()} view (`)) ?? "";
  const passed: string[] = [];
  const failed: string[] = [];
  const hdLimit = Number(/Hausdorff [\d.]+ mm \(needs <= ([\d.]+) mm\)/.exec(line)?.[1] ?? t.hausdorff_mm);
  const gap = `${v.view} view outline gap ${f2(v.hausdorff_mm)} mm`;
  (v.hausdorff_mm <= hdLimit + 1e-9 ? passed : failed).push(`${gap} ${v.hausdorff_mm <= hdLimit + 1e-9 ? "≤" : ">"} ${f2(hdLimit)} mm`);
  let notGated: string | null = null;
  if (/IoU [\d.]+ \(not gated\)/.test(line)) {
    notGated = `${v.view} view overlap ${v.iou.toFixed(3)} is reported but not gated (small silhouette)`;
  } else {
    const iouLimit = Number(/IoU [\d.]+ \(needs >= ([\d.]+)\)/.exec(line)?.[1] ?? t.iou);
    const ov = `${v.view} view overlap ${v.iou.toFixed(3)}`;
    (v.iou >= iouLimit - 1e-9 ? passed : failed).push(`${ov} ${v.iou >= iouLimit - 1e-9 ? "≥" : "<"} ${iouLimit}`);
  }
  const mean = /mean contour distance ([\d.]+) mm \(needs <= ([\d.]+) mm\)/.exec(line);
  if (mean) {
    const value = v.mean_mm ?? Number(mean[1]);
    const lim = Number(mean[2]);
    (value <= lim + 1e-9 ? passed : failed).push(`${v.view} view average edge gap ${f2(value)} mm ${value <= lim + 1e-9 ? "≤" : ">"} ${f2(lim)} mm`);
  }
  // the verifier's own verdict for the view wins over the recomputed comparison when it says the view fails
  const ok = line ? !/-\s*fails\s*$/.test(line) && failed.length === 0 : failed.length === 0;
  return { ok, passed, failed, notGated };
}

/**
 * What passed, what failed and what decided the status, for a record whose part tests all pass but whose status is
 * not verified (or any record): "Failed: side view outline gap 0.63 mm > 0.50 mm" next to "all 15 required part tests
 * passed" says plainly which check set the status. Null without a record or without views and tests.
 */
export function verdictBreakdown(v: VerdictRecord | null | undefined): VerdictBreakdown | null {
  if (!v || (!v.views.length && !v.tests.length)) return null;
  const passed: string[] = [];
  const failed: string[] = [];
  const notGated: string[] = [];
  const req = v.tests.filter((t) => (t.priority ?? "P0") === "P0");
  const reqFailed = req.filter((t) => !t.passed);
  if (req.length && !reqFailed.length) passed.push(req.length === 1 ? "the required part test" : `all ${req.length} required part tests`);
  else if (req.length) failed.push(...reqFailed.map((t) => `required test: ${t.description}${t.value != null ? ` (model ${f2(t.value)})` : ""}`));
  const failingViews: string[] = [];
  for (const view of v.views) {
    const c = checkView(view, v.reasons, v.thresholds);
    passed.push(...c.passed);
    failed.push(...c.failed);
    if (c.notGated) notGated.push(c.notGated);
    if (!c.ok) failingViews.push(`the ${view.view} view`);
  }
  const vetoes = (v.vetoes ?? []).filter((x) => x.severity === "blocking");
  for (const x of vetoes) failed.push(`blocking judge veto on ${x.feature.replaceAll("_", " ")}`);
  const causes = [...(reqFailed.length ? [`${reqFailed.length} required test${reqFailed.length === 1 ? "" : "s"}`] : []), ...failingViews, ...(vetoes.length ? ["the judge's blocking veto"] : [])];
  const status = v.status.replaceAll("_", " ");
  const decided = v.verified
    ? "Verified: every required test and every view passed."
    : causes.length
      ? `${status.charAt(0).toUpperCase()}${status.slice(1)} because of ${listWords(causes)}: verified needs every required test and every view to pass.`
      : `${status.charAt(0).toUpperCase()}${status.slice(1)}: see the verifier's notes.`;
  return { passed, failed, notGated, decided };
}

function listWords(xs: string[]): string {
  return xs.length <= 1 ? (xs[0] ?? "") : `${xs.slice(0, -1).join(", ")} and ${xs.at(-1)}`;
}

// ── verified, but right at the limit ────────────────────────────────────────────────────────────────────────────────

/** How close to the limit counts as "near it" (mm): a verified 0.49 mm against 0.50 mm. */
export const NEAR_LIMIT_MM = 0.01;

/** "Near the limit (0.49 mm of 0.50 mm): print the fit-test coupon first." for a verified record within
 * `NEAR_LIMIT_MM` of its limit; null otherwise. */
export function nearLimitNote(v: Pick<VerdictRecord, "verified" | "max_error_mm" | "thresholds"> | null | undefined): string | null {
  if (!v?.verified || v.max_error_mm == null) return null;
  const limit = v.thresholds.hausdorff_mm;
  if (v.max_error_mm < limit - NEAR_LIMIT_MM - 1e-9) return null;
  return `Near the limit (${f2(v.max_error_mm)} mm of ${f2(limit)} mm): print the fit-test coupon first.`;
}

// ── the 3D box vs the photo's length ────────────────────────────────────────────────────────────────────────────────

/**
 * When the model's box (its own X, Y, Z) and the length test's numbers differ by more than the test's tolerance, one
 * sentence that says they are different measurements. Null when they agree or a number is missing.
 */
export function boxVsPhotoNote(v: Pick<VerdictRecord, "validity" | "tests"> | null | undefined): string | null {
  const box = v?.validity?.bbox_mm;
  const len = v?.tests.find((t) => t.id === "bbox.x");
  if (!box || !len || len.value == null || len.expected == null) return null;
  const longSide = Math.max(box[0], box[1]);
  if (Math.abs(longSide - len.value) <= (len.tol ?? 0.3)) return null;
  const dims = box.map((x) => x.toFixed(1)).join(" × ");
  return (
    `The size on the 3D view (${dims} mm) is the model's box in its own X, Y and Z. The length test measures the long side ` +
    `of the footprint as the top photo sees it: code renders the model with the photo's camera and measures it with the ` +
    `same code (model ${f2(len.value)} mm, photo ${f2(len.expected)} mm, ${len.passed ? "passed" : "failed"}). ` +
    `They are different measurements, so they need not match.`
  );
}

// ── a thickness the user stated, next to a different photo number ───────────────────────────────────────────────────

/**
 * When the thickness was user-stated: how it was used and what checked it (the model against the stated value, not the
 * photo), and what the side photo's number is (the short side of its silhouette, compared with the model's own side
 * outline). Null when the thickness was measured or no test used it.
 */
export function statedThicknessNote(v: Pick<VerdictRecord, "residuals"> | null | undefined, thicknessSource: string | null | undefined): string | null {
  if (thicknessSource !== "user_stated") return null;
  const plate = v?.residuals?.find((r) => r.feature_id === "plate" && r.quantity === "thickness");
  if (!plate) return null;
  const side = v?.residuals?.find((r) => r.feature_id === "side" && r.quantity === "thickness");
  const head =
    `Thickness ${f2(plate.measured_mm)} mm is the number you gave, used as given: the model was built to it and its test ` +
    `only checks that the model matches what you said (model ${f2(plate.model_mm)} mm), not the photo.`;
  if (!side) return head;
  return (
    `${head} The side photo's ${f2(side.measured_mm)} mm is a different measurement, the short side of its silhouette; ` +
    `its test compares the model's side outline (${f2(side.model_mm)} mm) with it, within ±${f2(side.tol_mm)} mm ` +
    `(${side.passed ? "passed" : "failed"}).`
  );
}

// ── install-card steps ───────────────────────────────────────────────────────────────────────────────────────────────

/** Families whose part moves in use (a hinge swings, a wheel turns, a latch clicks); the rest sit still. */
export const MOVING_FAMILIES: ReadonlySet<string> = new Set(["hinge", "wheel", "gear", "knob", "latch", "clip"]);

/** A note when an install card's steps (written into the generated images) talk about movement for a part that does
 * not move; null otherwise. */
export function installStepsNote(family: string | null | undefined, labels: readonly string[]): string | null {
  if (!family || MOVING_FAMILIES.has(family)) return null;
  if (!labels.some((l) => /\bmoves?\b/i.test(l))) return null;
  return `The step text was written into the images from fixed steps for moving parts. A ${family.replaceAll("_", " ")} does not move: check that it sits flush and holds like the original.`;
}

/** "install card 2/3: Fit the …" → { step: 2, of: 3, text: "Fit the …", mock }; null for other labels. */
export function installPanel(label: string): { step: number; of: number; text: string; mock: boolean } | null {
  const m = /install card (\d+)\s*\/\s*(\d+)\s*:?\s*(.*)$/i.exec(label.trim());
  if (!m) return null;
  const mock = /\(mock\)\s*$/i.test(m[3]!);
  return { step: Number(m[1]), of: Number(m[2]), text: m[3]!.replace(/\s*\(mock\)\s*$/i, "").trim(), mock };
}
