import { expect, test, type Page } from "@playwright/test";
import { asAdmin, expectAccessible, realErrors, setup, shot } from "./helpers";

const functional = (name: string) => name === "desktop-light";

async function noSideScroll(page: Page) {
  const vw = page.viewportSize()!.width;
  expect(await page.evaluate((w) => document.documentElement.scrollWidth - w, vw), "no horizontal page scroll").toBeLessThanOrEqual(0);
}

test("playground gallery and workbench render, accessible, no sideways scroll, no console errors", async ({ page }, info) => {
  const { errors } = await setup(page);
  await page.goto("/playground");
  await expect(page.getByRole("heading", { name: "Every part is a program with knobs", level: 1 })).toBeVisible();
  await expect(page.getByRole("list", { name: "Example parts" }).getByRole("listitem")).toHaveCount(10);
  await page.waitForLoadState("networkidle");
  await noSideScroll(page);
  await shot(page, info, "playground");
  await expectAccessible(page);
  await page.goto("/playground?t=cable_clip&hole_d=3.4");
  await expect(page.getByRole("heading", { name: "Cable clip", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "This is the program" })).toBeVisible();
  await expect(page.getByRole("button", { name: "M3 screw" })).toHaveAttribute("aria-pressed", "true");
  await page.waitForLoadState("networkidle");
  await noSideScroll(page);
  await shot(page, info, "playground-cable-clip");
  await expectAccessible(page);
  expect(realErrors(errors)).toEqual([]);
});

test("describe: form, result and no-fit render, accessible, no console errors", async ({ page }, info) => {
  const { errors } = await setup(page);
  await page.goto("/describe");
  await expect(page.getByRole("heading", { name: "Describe it, with your numbers", level: 1 })).toBeVisible();
  await expect(page.getByLabel("What do you need? Say the numbers you know.")).toBeVisible();
  // the example is the server's stored result for its own sentence: the numbers it says are tagged "you said"
  const ex = page.getByTestId("describe-example");
  await expect(ex).toContainText("A spacer 12 mm tall for an M3 screw, outer diameter 7 mm");
  await expect(ex.getByText("you said", { exact: true })).toHaveCount(3);
  await expect(ex).toContainText("Height 12 mm");
  await expect(ex).toContainText("Matches your numbers");
  await expect(page.getByText("run on this server · mock planner, no model call")).toBeVisible();
  await noSideScroll(page);
  await shot(page, info, "describe");
  await expectAccessible(page);
  await page.goto("/describe?id=d_261031_0000done");
  await expect(page.getByText("Matches your numbers").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await noSideScroll(page);
  await shot(page, info, "describe-result");
  await expectAccessible(page);
  expect(realErrors(errors)).toEqual([]);
});

test.describe("functional", () => {
  test.beforeEach(({}, info) => {
    test.skip(!functional(info.project.name), "functional flows run once");
  });

  test("playground: presets set the knobs, the URL and the program; files need the acknowledgement", async ({ page }) => {
    await setup(page);
    await page.goto("/playground");
    await page.getByRole("button", { name: /^Cable clip \d+ knobs/ }).click();
    await expect(page).toHaveURL(/\/playground\?t=cable_clip$/);
    await expect(page.getByRole("button", { name: "Reset", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "M4 screw" }).click();
    await expect(page).toHaveURL(/hole_d=4\.5/);
    const line = page.locator('[data-knob="hole_d"]').first();
    await expect(line).toContainText('"hole_d": (4.5,');
    await expect(page.getByText(/1 value changed/)).toBeVisible();
    const stl = page.getByRole("region", { name: "Print it" }).locator("a", { hasText: "STL" });
    await expect(stl).toHaveAttribute("aria-disabled", "true");
    await page.getByLabel("I understand: these files are not checked against a real part.").check();
    await expect(stl).toHaveAttribute("href", /\/api\/v1\/templates\/cable_clip\/bake\?.*hole_d=4\.5.*download=1.*ack=1/);
    await expect(page.getByRole("link", { name: /part\.py/ })).toHaveAttribute("href", /format=py/);
    await page.getByRole("button", { name: "Reset", exact: true }).click();
    await expect(page).toHaveURL(/\/playground\?t=cable_clip$/);
    await page.getByRole("button", { name: "All examples" }).click();
    await expect(page.getByRole("list", { name: "Example parts" })).toBeVisible();
  });

  test("describe: words → result with tagged knobs, checks, photo link and print panel", async ({ page }) => {
    const { log } = await setup(page);
    await page.goto("/describe");
    await page.getByRole("button", { name: /A cable clip for a 6 mm cable, screws down with one M3 screw/ }).click();
    await page.getByLabel("What do you need? Say the numbers you know.").fill("a cable clip for a 6 mm cable, screws down with one M3 screw, 20 mm wide, 45 mm long");
    await page.getByRole("button", { name: "Make it" }).click();
    await expect(page).toHaveURL(/\/describe\?id=d_261031_0000done/);
    await expect(page.getByRole("heading", { name: "Your numbers vs the built model" })).toBeVisible();
    await expect(page.getByText("Matches your numbers").first()).toBeVisible();
    await expect(page.getByText("not verified: no photo")).toBeVisible();
    const cable = page.locator('[data-knob="cable_d"]');
    await expect(cable.getByText("you said", { exact: true })).toBeVisible();
    await expect(page.locator('[data-knob="wall"]').getByText("default", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Add a photo to verify it against the real part" })).toHaveAttribute("href", /^\/fix\?family=cable_clip&intent=/);
    await expect(page.getByRole("region", { name: "Print it" }).getByText("Orientation")).toBeVisible();
    await page.getByRole("region", { name: "Print it" }).getByLabel("Your city").fill("Pune");
    await page.getByRole("region", { name: "Print it" }).getByRole("button", { name: "Search" }).click();
    await expect(page.getByText("No web search ran (no search key on this server), so no shop is listed.")).toBeVisible();
    expect(log.some((l) => l.startsWith("POST /print-shops"))).toBe(true);
  });

  test("describe: missing numbers become questions; no template → plain words and the way out", async ({ page }) => {
    await setup(page);
    await page.goto("/describe?id=d_261031_0000asks");
    await expect(page.getByRole("heading", { name: "A few numbers are missing" })).toBeVisible();
    await page.getByLabel(/Base length/).fill("long");
    await page.getByRole("button", { name: "Build it" }).click();
    await expect(page.getByText("Type a number, or leave it empty.")).toBeVisible();
    await page.getByLabel(/Base length/).fill("45");
    await page.getByRole("button", { name: "Build it" }).click();
    await expect(page.getByText("Matches your numbers").first()).toBeVisible();
    await page.goto("/describe?id=d_261031_000nofit");
    await expect(page.getByText("No part program fits this description")).toBeVisible();
    await expect(page.getByRole("link", { name: "Ask for this part on the requests board" })).toHaveAttribute("href", "/requests");
  });

  test("fix: first-visit guide, dismissed and remembered, links to describe", async ({ page }) => {
    await setup(page);
    await page.goto("/fix");
    const guide = page.getByRole("region", { name: "First time? Three steps to a measured part" });
    await expect(guide.getByRole("listitem")).toHaveCount(3);
    await expect(guide.getByRole("link", { name: /No part in hand\? Describe it/ })).toHaveAttribute("href", "/describe");
    await guide.getByRole("button", { name: "Got it" }).click();
    await page.reload();
    await expect(page.getByRole("button", { name: "Show the 3-step guide" })).toBeVisible();
    await expect(page.getByRole("region", { name: /First time/ })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /No part in hand\? Describe it/ })).toBeVisible();
  });

  test("part page: make a variant — admins save it (labelled best effort), the files follow the knobs", async ({ page }) => {
    await asAdmin(page);
    const { log } = await setup(page);
    await page.goto("/parts/l-bracket?thickness=5");
    const box = page.locator("#make-variant");
    await expect(box.getByText("1 knob changed")).toBeVisible();
    await expect(box.getByText("A variant of a verified part, not itself checked against a photo.")).toBeVisible();
    await expect(box.getByRole("link", { name: "STL" })).toHaveAttribute("href", /\/parts\/l-bracket\/bake\?.*thickness=5.*download=1/);
    await box.getByRole("button", { name: "Save as a variant" }).click();
    await expect(box.getByText("Saved as")).toBeVisible();
    await expect(box.getByRole("link", { name: "Open the variant" })).toHaveAttribute("href", "/parts/l-bracket-variant");
    expect(log.some((l) => l.startsWith("POST /parts/l-bracket/variants"))).toBe(true);
  });

  test("job page: Print it with settings from the backend, and Make a variant", async ({ page }) => {
    await setup(page);
    await page.goto("/jobs/job_demo_1");
    const panel = page.getByRole("region", { name: "Print it" });
    await expect(panel.getByText("Layer · walls · infill")).toBeVisible();
    await expect(panel.getByText("Orientation", { exact: true })).toBeVisible();
    // the load note defers to the computed orientation instead of giving a second instruction
    await expect(panel.getByTestId("load-note")).toContainText("Computed print orientation:");
    await expect(page.getByRole("heading", { name: "Make a variant" })).toBeVisible();
  });

  test("an older backend without these routes gets a plain message, not a broken page", async ({ page }) => {
    await setup(page);
    await page.route("**/api/v1/openapi.json", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ openapi: "3.1.0", paths: {} }) }));
    await page.goto("/playground");
    await expect(page.getByText("The playground is not on this server yet")).toBeVisible();
    await page.goto("/describe");
    await expect(page.getByText("Describe it is not on this server yet")).toBeVisible();
  });
});
