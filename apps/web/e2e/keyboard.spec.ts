import { expect, test, type Page } from "@playwright/test";
import { asAdmin, setup } from "./helpers";

test.beforeEach(({}, info) => {
  test.skip(info.project.name !== "desktop-light", "keyboard checks run once");
});

async function tabUntil(page: Page, name: RegExp, max = 60) {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    const label = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      return el ? el.getAttribute("aria-label") ?? el.textContent ?? "" : "";
    });
    if (name.test(label)) return i;
  }
  throw new Error(`never reached ${name}`);
}

test("/fix: focus order follows the steps", async ({ page }) => {
  await setup(page);
  await page.goto("/fix");
  await page.getByRole("link", { name: "Try a synthetic sample" }).focus();
  const a = await tabUntil(page, /Screen mat/);
  const b = await tabUntil(page, /Choose file: top view/);
  const c = await tabUntil(page, /^$|What broke/); // the intent textarea has no text content
  await expect(page.getByLabel("What broke, and what should change?")).toBeFocused();
  const d = await tabUntil(page, /Start the fix/);
  expect([a, b, c, d].every((x) => x >= 0)).toBe(true);
});

test("/calibrate is keyboard-operable", async ({ page }) => {
  await setup(page, { calibrated: false });
  await page.goto("/calibrate");
  const card = page.getByRole("slider", { name: "Card width on screen" });
  await card.focus();
  const before = Number(await card.getAttribute("aria-valuenow"));
  await page.keyboard.press("Shift+ArrowRight");
  await expect(card).toHaveAttribute("aria-valuenow", String(before + 10));
  await page.keyboard.press("Enter");
  await expect(page.getByText("Screen calibrated").first()).toBeVisible();
});

test("/mat: stage radios work with arrow keys, Esc leaves", async ({ page }) => {
  await setup(page);
  await page.goto("/mat");
  const light = page.getByRole("radio", { name: /light/i });
  await light.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio", { name: /dark/i })).toHaveAttribute("aria-checked", "true");
  await expect(page.locator('svg rect[fill="#303030"]')).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/\/fix$/);
});

test("knobs: arrow keys re-bake, steppers and numeric entry work", async ({ page }) => {
  const { log } = await setup(page);
  await page.goto("/parts/l-bracket");
  const slider = page.getByRole("slider", { name: "Leg thickness" });
  await slider.focus();
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => log.some((l) => l.includes("/parts/l-bracket/bake") && l.includes("thickness=3.1"))).toBeTruthy();
  await page.getByRole("button", { name: "Increase Holes in the base leg" }).press("Enter");
  await expect.poll(() => log.some((l) => l.includes("base_holes=3"))).toBeTruthy();
  const input = page.getByLabel("Screw hole diameter in millimetres");
  await input.fill("5");
  await input.press("Enter");
  await expect.poll(() => log.some((l) => l.includes("hole_d=5"))).toBeTruthy();
});

test("steer queue: focusable listbox, arrows move, keys review", async ({ page }) => {
  await asAdmin(page);
  const { log } = await setup(page);
  await page.goto("/factory?id=steer_1");
  const lb = page.getByRole("listbox", { name: /Approval queue/ });
  await lb.focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("option", { name: /Shelf support pin/ })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("s");
  await expect.poll(() => log.some((l) => l.startsWith("POST /steer/steer_1/review"))).toBeTruthy();
});
