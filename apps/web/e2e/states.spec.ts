import { expect, test, type Page } from "@playwright/test";
import { expectAccessible, realErrors, setup } from "./helpers";

const contentProject = (name: string) => name.startsWith("desktop-light") || name.startsWith("mobile-dark");

async function fails(page: Page, url: string | RegExp) {
  let down = true;
  await page.route(url, (route) => (down ? route.fulfill({ status: 503, contentType: "application/json", body: '{"error":{"code":"down","message":"down"}}' }) : route.fallback()));
  return () => {
    down = false;
  };
}

test.beforeEach(({}, info) => {
  test.skip(!contentProject(info.project.name), "states are the same in every theme");
});

test("/proof: when the evidence can't load it says so, and Try again brings it back", async ({ page }) => {
  await setup(page);
  const recover = await fails(page, "**/api/v1/proof");
  await page.goto("/proof");
  const retry = page.getByRole("button", { name: /try again/i });
  await expect(retry).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("17/17 blocked")).toHaveCount(0);
  recover();
  await retry.click();
  await expect(page.getByText("17/17 blocked")).toBeVisible();
});

test("/gallery: the registry and the templates fail on their own, with nothing invented in their place", async ({ page }) => {
  await setup(page);
  const recover = await fails(page, /\/api\/v1\/parts(\?|$)/);
  await page.goto("/gallery");
  await expect(page.getByText("Template · not checked against a real part").first()).toBeVisible();
  const retry = page.getByRole("region", { name: "Registry parts" }).getByRole("button", { name: /try again/i });
  await expect(retry).toBeVisible({ timeout: 20_000 });
  await expectAccessible(page);
  recover();
  await retry.click();
  await expect(page.getByRole("link", { name: /L-bracket/ }).first()).toBeVisible();
});

test("/gallery: an empty registry says so and points to the templates", async ({ page }) => {
  await setup(page, { emptyRegistry: true });
  await page.goto("/gallery");
  await expect(page.getByText("No parts published on this server yet")).toBeVisible();
});

test("/how: with the run's data missing the pictures stay and the numbers say they did not load", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/deck/data.json", (route) => route.fulfill({ status: 404, body: "" }));
  await page.goto("/how");
  const steps = page.getByRole("region", { name: "The eight steps" });
  await steps.getByRole("tab", { name: "Check" }).click();
  const panel = steps.getByRole("tabpanel");
  await expect(panel.getByText("did not load")).toBeVisible();
  await expect(panel.locator("img")).toBeVisible();
  await expect(panel).not.toContainText(/\d+ of \d+ times/);
  await steps.getByRole("tab", { name: "Program" }).click();
  await expect(panel.getByText("did not load")).toBeVisible();
  expect(realErrors(errors).filter((e) => !e.includes("404"))).toEqual([]);
});

test("/how on a phone: no step pushes the page sideways, and each picture fits", async ({ page }, info) => {
  test.skip(!info.project.name.startsWith("mobile"), "phone width");
  await setup(page);
  await page.goto("/how");
  const steps = page.getByRole("region", { name: "The eight steps" });
  const tabs = steps.getByRole("tab");
  const vw = page.viewportSize()!.width;
  for (let i = 0; i < 8; i++) {
    await tabs.nth(i).click();
    await expect(steps.getByRole("tabpanel").getByText(`Step ${i + 1} of 8`)).toBeVisible();
    expect(await page.evaluate((w) => document.documentElement.scrollWidth - w, vw), `step ${i + 1}`).toBeLessThanOrEqual(0);
    for (const box of await steps.getByRole("tabpanel").locator("img").evaluateAll((els) => els.map((e) => e.getBoundingClientRect().right))) {
      expect(box).toBeLessThanOrEqual(vw);
    }
  }
});

test("keyboard: Tab reaches a step and its panel, arrows change step, and the focused word explains itself", async ({ page }, info) => {
  test.skip(info.project.name.startsWith("mobile"), "a keyboard");
  await setup(page);
  await page.goto("/how");
  const steps = page.getByRole("region", { name: "The eight steps" });
  await expect(steps.getByRole("tab", { name: "Photo" })).toHaveAttribute("aria-selected", "true");
  await steps.getByRole("tab", { name: "Photo" }).focus();
  await page.keyboard.press("End");
  await expect(steps.getByRole("tab", { name: "Review" })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Home");
  await expect(steps.getByRole("tab", { name: "Photo" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(steps.getByRole("tabpanel")).toBeFocused();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  const word = steps.getByRole("tabpanel").getByRole("button", { name: "mat", exact: true });
  await word.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("tooltip")).toContainText("true size");
});

test("/gallery holds off the 3D until a card is near the screen", async ({ page }, info) => {
  test.skip(info.project.name.startsWith("mobile"), "a tall list on one screen");
  await setup(page);
  await page.goto("/gallery");
  await expect(page.getByText("Template · not checked against a real part").first()).toBeAttached();
  const cards = await page.locator('a[href^="/playground?t="], a[href^="/parts/"]').count();
  expect(cards).toBeGreaterThan(6);
  await expect.poll(() => page.locator("canvas").count()).toBeLessThan(cards);
});
