import { expect, test } from "@playwright/test";
import { setup } from "./helpers";

test.beforeEach(({}, info) => {
  test.skip(info.project.name !== "desktop-light", "functional checks run once");
});

test("landing: the median sits next to how many of the same cases passed verification", async ({ page }) => {
  await setup(page);
  await page.goto("/");
  const ticker = page.getByRole("list", { name: "Numbers from this server" });
  await expect(ticker).toContainText("median size error");
  await expect(ticker).toContainText("34/40");
  await expect(ticker).toContainText("passed verification");
  await expect(ticker).not.toContainText("recorded runs");
  await expect(page.getByText("34 of 40 passed verification (all checks within limits)")).toBeAttached();
});

test("parts: honest heading with the verified count, and a best-effort card says why", async ({ page }) => {
  await setup(page);
  await page.goto("/parts");
  await expect(page.getByRole("heading", { level: 1, name: "Parametric parts" })).toBeVisible();
  await expect(page.getByText(/\d+ of \d+ verified by code against their photos/)).toBeVisible();
  await expect(page.getByText("Why: the top outline is off by up to 0.83 mm (limit 0.50 mm)")).toBeVisible();
});

test("job: a best-effort verdict names the failed check; See the fix never shows a mock picture", async ({ page }) => {
  await setup(page);
  await page.goto("/jobs/job_best");
  await expect(page.getByText("Why: the top outline is off by up to 0.83 mm (limit 0.50 mm).")).toBeVisible();
  await page.getByRole("button", { name: "See the fix" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("No picture of the fix on this server");
  await expect(dialog.getByRole("img", { name: /of the repaired part/ })).toHaveCount(0);
});

test("a missing part offers the way back instead of Try again", async ({ page }) => {
  await setup(page);
  await page.goto("/parts/no-such-part");
  await expect(page.getByRole("link", { name: "Browse all parts" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toHaveCount(0);
});
