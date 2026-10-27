/**
 * Live photo-fix flow: upload a sample top photo through /fix → capture gate → job → answer the paused questions →
 * verdict → text edit → "see the fix" preview → screen fit-check outline. Run with `pnpm e2e:live`.
 * Note: the backend labels uploads origin "real"; this test uploads a bundled synthetic render.
 */
import { expect, test } from "@playwright/test";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { watchErrors } from "./watch";

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = join(here, "..", "..", "..", "..");
const PHOTO = join(ROOT, "data/synthetic/samples/demo-knob/top.jpg");

test("fix upload → questions → verdict → edit → preview → fit outline", async ({ page }) => {
  test.setTimeout(300_000);
  const errors = watchErrors(page);
  await page.addInitScript(() => {
    const c = { px_per_mm: 3.7795, dpr: window.devicePixelRatio, screen_w: window.screen.width, screen_h: window.screen.height, card_w_px: 323.5, card_h_px: 204, calibrated_at: Date.now() };
    window.localStorage.setItem("partsmith.screen-calibration.v1", JSON.stringify(c));
  });

  await page.goto("/fix");
  await page.getByLabel("Upload Top view photo").setInputFiles(PHOTO);
  await expect(page.getByText(/Capture gate passed|Retake this photo/).first()).toBeVisible({ timeout: 60_000 });
  await page.getByLabel("What broke, and what should change?").fill("The knob slips on the shaft; keep the size.");
  await page.getByRole("button", { name: "Start the fix" }).click();
  await page.waitForURL(/\/jobs\/j_[^/]+$/, { timeout: 30_000 });

  // Answer every question the job pauses on (default value, typed).
  const verdict = page.getByRole("status", { name: /^(Verified|Best effort|Failed)/ });
  for (let i = 0; i < 6; i++) {
    const q = page.getByRole("region", { name: /.+/ }).filter({ has: page.getByText("Paused — needs your answer") });
    const which = await Promise.race([
      q.waitFor({ timeout: 120_000 }).then(() => "question" as const),
      verdict.waitFor({ timeout: 120_000 }).then(() => "done" as const),
    ]);
    if (which === "done") break;
    const input = q.getByRole("textbox").first();
    if ((await input.inputValue()) === "") await input.fill("16");
    await q.getByRole("button", { name: "Answer" }).click();
    await expect(q).toBeHidden({ timeout: 60_000 });
  }
  await expect(verdict).toBeVisible({ timeout: 180_000 });

  // Text edit: words → clamped knob changes + bake.
  await page.getByLabel("Describe an edit").fill("make it 2 mm taller");
  await page.getByRole("button", { name: "Apply edit" }).click();
  await expect(page.getByText("Heard:")).toBeVisible({ timeout: 60_000 });

  // "See the fix" is labelled as a generated preview.
  await page.getByRole("button", { name: "See the fix" }).click();
  // The label comes from the API ("AI preview", or a MOCK PREVIEW label in mock mode) and is always shown.
  await expect(page.getByRole("dialog").getByRole("img", { name: /preview/i })).toBeVisible({ timeout: 60_000 });
  await page.keyboard.press("Escape");

  // Screen fit check draws the 1:1 outline in the segmenter's background colour.
  await page.getByRole("link", { name: "Screen fit check" }).click();
  await expect(page.locator('polygon[stroke="#E0218A"]')).toHaveCount(1, { timeout: 30_000 });
  expect(errors, errors.join("\n")).toEqual([]);
});
