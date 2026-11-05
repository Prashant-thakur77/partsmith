import { expect, test } from "@playwright/test";
import { expectAccessible, realErrors, setup } from "./helpers";

const contentProject = (name: string) => name.startsWith("desktop-light") || name.startsWith("mobile-light");

async function pageIsClean(page: import("@playwright/test").Page, errors: string[]) {
  await page.waitForLoadState("networkidle");
  const vw = page.viewportSize()!.width;
  expect(await page.evaluate((w) => document.documentElement.scrollWidth - w, vw), "no sideways scroll").toBeLessThanOrEqual(0);
  await expectAccessible(page);
  expect(realErrors(errors)).toEqual([]);
}

test("/proof leads with what is not tested, and every result names its truth and command", async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto("/proof");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("What has been tested");
  await expect(page.getByRole("heading", { name: "Not tested yet" })).toBeVisible();
  await expect(page.getByText("Real phone photos of a part on a laptop screen, measured")).toBeVisible();
  await expect(page.getByText("17/17 blocked")).toBeVisible();
  await expect(page.getByText("ground truth for bypass")).toBeVisible();
  await expect(page.getByText(/not phone captures/).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /eval\/reports\/latest\/bypass|report\.json/ }).first()).toHaveAttribute("href", /github\.com.*eval\/reports\/latest/);
  await expect(page.getByRole("region", { name: "Verified parts against ground truth" })).toContainText("Intact parts, top photo only");
  await expect(page.getByRole("region", { name: "Test suites table" })).toContainText("1023/1023");
  await expect(page.getByRole("region", { name: "Test suites table" })).toContainText("not run");
  await expect(page.getByText("20 → 35")).toBeVisible();
  await pageIsClean(page, errors);
});

test("/compare: the same part, stretched against rebuilt, with the numbers following the slider", async ({ page }, info) => {
  const { errors } = await setup(page);
  await page.goto("/compare");
  const table = page.getByRole("region", { name: "Stretching against the knob, in numbers" });
  await expect(table).toContainText("Hole spacing shift");
  await expect(table.getByRole("row", { name: /Hole spacing shift/ })).toContainText("0.00 mm");
  if (contentProject(info.project.name)) {
    const slider = page.getByRole("slider", { name: "Target hole diameter" });
    await slider.focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    const row = table.getByRole("row", { name: /Hole spacing shift/ });
    await expect(row).not.toContainText("0.00 mm 0.00 mm");
    await page.getByRole("button", { name: "Longer plate" }).click();
    await page.getByRole("slider", { name: "Target plate length" }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(table.getByRole("row", { name: /Hole shape/ })).toContainText(/oval/);
    await expect(table.getByRole("row", { name: /Hole shape/ })).toContainText("round");
  }
  const today = page.getByRole("region", { name: "Comparison table" });
  await expect(today).toContainText("AI image-to-3D");
  await expect(today).toContainText("Yes, by code");
  await expect(page.getByText(/We found none that check the result/)).toBeVisible();
  await expect(page.getByText("2.77 mm against 0 mm")).toBeVisible();
  await pageIsClean(page, errors);
});

test("/gallery shows parts and templates with their status, and labels templates as unchecked", async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto("/gallery");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Every part, in 3D");
  await expect(page.getByRole("heading", { name: "Registry parts" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Templates" })).toBeVisible();
  await expect(page.getByText("Template · not checked against a real part").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /L-bracket/ }).first()).toHaveAttribute("href", /\/parts\//);
  await pageIsClean(page, errors);
  // a template opens on its own knobs, not on the list of examples
  await page.locator('a[href="/playground?t=cable_clip"]').click();
  await expect(page.getByRole("heading", { name: "Cable clip", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "This is the program" })).toBeVisible();
});

test("the header and footer lead to the new pages", async ({ page }, info) => {
  test.skip(!info.project.name.startsWith("desktop-light"), "desktop nav");
  await setup(page);
  await page.goto("/proof");
  await expect(page.getByRole("navigation").getByRole("link", { name: "Proof", exact: true }).first()).toHaveAttribute("href", "/proof");
  const footer = page.getByRole("contentinfo");
  await expect(footer.getByRole("link", { name: "Gallery" })).toHaveAttribute("href", "/gallery");
  await expect(footer.getByRole("link", { name: "Compare" })).toHaveAttribute("href", "/compare");
  await expect(footer.getByRole("link", { name: "Test evidence" })).toHaveAttribute("href", "/proof");
});

test("a visitor without the owner's token sees why publishing isn't offered", async ({ page }, info) => {
  test.skip(!info.project.name.startsWith("desktop-light"), "behaviour check");
  await setup(page);
  await page.goto("/jobs/job_best");
  await expect(page.getByText("Publishing needs the site owner's token.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Publish" })).toHaveCount(0);
});
