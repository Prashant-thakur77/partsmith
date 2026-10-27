import { fileURLToPath as __f2p } from "node:url";
import { dirname as __dn } from "node:path";
const __dirname = __dn(__f2p(import.meta.url));
import { expect, test } from "@playwright/test";
import { join } from "node:path";
import { asAdmin, realErrors, setup } from "./helpers";

test.beforeEach(({}, info) => {
  test.skip(info.project.name !== "desktop-light", "functional flows run once");
});

test("landing knob drag re-bakes through the API and shows bake status", async ({ page }) => {
  const { log, errors } = await setup(page);
  await page.goto("/");
  const knob = page.getByRole("slider", { name: "Base leg length" });
  await knob.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => log.some((l) => l.startsWith("GET /parts/l-bracket/bake") && l.includes("length=40.2"))).toBeTruthy();
  await expect(page.getByText(/baked · 640 ms/)).toBeVisible();
  expect(realErrors(errors)).toEqual([]);
});

test("fix flow: photo → capture gate → start job → workspace", async ({ page }) => {
  const { log } = await setup(page);
  await page.goto("/fix");
  await page.getByLabel("Upload Top view photo").setInputFiles(join(__dirname, "fixtures/generated/photo.png"));
  await expect(page.getByText("Capture gate passed").first()).toBeVisible();
  await page.getByLabel("What broke, and what should change?").fill("Same size, stronger.");
  await page.getByLabel("Thickness, if you know it").fill("3.2");
  await page.getByRole("button", { name: "Start the fix" }).click();
  await expect(page).toHaveURL(/\/jobs\/job_demo_1$/);
  expect(log.some((l) => l.startsWith("POST /jobs/fix"))).toBeTruthy();
  expect(log.some((l) => l.startsWith("POST /measure"))).toBeTruthy();
});

test("workspace streams events, ends verified and exposes exports", async ({ page }) => {
  await setup(page);
  await page.goto("/jobs/job_demo_1");
  await expect(page.getByRole("status", { name: /Verified, max error 0\.31/ })).toBeVisible();
  await page.getByRole("tab", { name: "Residuals" }).click();
  const firstRow = page.locator("table").first().locator("tbody tr").first();
  await expect(firstRow).toContainText("hole_1");
  await expect(firstRow).toContainText("0.19");
  await page.getByRole("button", { name: "Export" }).click();
  await expect(page.getByRole("menuitem", { name: /STL/ })).toBeVisible();
});

test("paused job: answering the question posts the value in mm", async ({ page }) => {
  const { log } = await setup(page);
  await page.goto("/jobs/job_paused");
  await page.getByLabel("Answer in millimetres").fill("11.5");
  await page.getByRole("button", { name: "Answer" }).click();
  await expect.poll(() => log.some((l) => l.startsWith("POST /jobs/job_paused/answer"))).toBeTruthy();
});

test("calibration saves px/mm and the mat draws the markers", async ({ page }) => {
  await setup(page, { calibrated: false });
  await page.goto("/mat");
  await expect(page.getByRole("heading", { name: "Calibrate this screen first" })).toBeVisible();
  await page.goto("/calibrate");
  const card = page.getByRole("slider", { name: "Card width on screen" });
  await card.focus();
  await page.keyboard.press("Shift+ArrowRight");
  await page.getByRole("button", { name: "Save calibration" }).click();
  await page.goto("/mat");
  const mat = page.getByRole("img", { name: /1:1 scale/ });
  await expect(mat).toBeVisible();
  const w = await mat.evaluate((el) => el.getBoundingClientRect().width);
  expect(w).toBeGreaterThan(300);
});

test("steer queue keyboard shortcut approves the selected part", async ({ page }) => {
  await asAdmin(page);
  const { log } = await setup(page);
  await page.goto("/factory?id=steer_1");
  await expect(page.getByRole("option", { name: /Cupboard latch/ })).toBeVisible();
  await page.keyboard.press("a");
  await expect.poll(() => log.some((l) => l.startsWith("POST /steer/steer_1/review"))).toBeTruthy();
});

test("registry search filters and offers a need when nothing matches", async ({ page }) => {
  const { log } = await setup(page);
  await page.goto("/parts");
  await page.getByLabel("Search parts").fill("zzz nothing");
  await expect(page.getByRole("button", { name: "Request this part" })).toBeVisible();
  await page.getByRole("button", { name: "Request this part" }).click();
  await expect.poll(() => log.some((l) => l.startsWith("POST /needs"))).toBeTruthy();
});

test("theme toggle switches to dark without reload", async ({ page }) => {
  await setup(page);
  await page.goto("/");
  await expect(page.getByRole("link", { name: /API online/ })).toBeVisible(); // hydrated
  await page.getByRole("radio", { name: "Dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("contrast failure offers the dark stage in one click, and the mat draws it", async ({ page }) => {
  await setup(page, { contrastFail: true });
  await page.goto("/fix");
  await page.getByLabel("Upload Top view photo").setInputFiles(join(__dirname, "fixtures/generated/photo.png"));
  const link = page.getByRole("link", { name: "Open mat with dark stage" });
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", "/mat?stage=dark");
  await page.goto("/mat?stage=dark");
  await expect(page.getByRole("radio", { name: /dark/i })).toHaveAttribute("aria-checked", "true");
  await expect(page.locator('svg rect[fill="#303030"]')).toHaveCount(1);
  // persisted per device
  await page.goto("/mat");
  await expect(page.locator('svg rect[fill="#303030"]')).toHaveCount(1);
  await page.getByRole("radio", { name: /light/i }).click();
  await expect(page.locator('svg rect[fill="#303030"]')).toHaveCount(0);
});
