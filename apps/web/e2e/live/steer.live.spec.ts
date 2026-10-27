/** Live steer run: brief → plan → lanes build → approve the first queued part with the keyboard. `pnpm e2e:live`. */
import { expect, test } from "@playwright/test";
import { watchErrors } from "./watch";

test("steer: brief → lanes → approve with the 'a' key → published", async ({ page }) => {
  test.setTimeout(240_000);
  const errors = watchErrors(page);
  await page.goto("/steer");
  await page.getByLabel("Brief").fill("Cable clips for a desk, 6 and 8 mm cables");
  await page.getByRole("spinbutton", { name: "Parts" }).fill("2");
  await page.getByRole("button", { name: "Plan and build" }).click();
  await page.waitForURL(/\/steer\?id=s_/, { timeout: 30_000 });
  const first = page.getByRole("option").first();
  await expect(first).toBeVisible({ timeout: 180_000 });
  const title = (await first.locator("div.truncate").first().textContent())?.trim() ?? "";
  await page.locator("h1").first().click(); // move focus out of form fields; shortcuts ignore inputs
  await page.keyboard.press("a");
  await expect(page.getByText(/Approved/).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(new RegExp(`${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} · published`))).toBeVisible({ timeout: 30_000 });
  expect(errors, errors.join("\n")).toEqual([]);
});
