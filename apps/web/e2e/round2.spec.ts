import { fileURLToPath as __f2p } from "node:url";
import { dirname as __dn } from "node:path";
const __dirname = __dn(__f2p(import.meta.url));
import { expect, test } from "@playwright/test";
import { join } from "node:path";
import { asAdmin, realErrors, setup } from "./helpers";

test.beforeEach(({}, info) => {
  test.skip(info.project.name !== "desktop-light", "functional flows run once");
});

test("old routes redirect to the plain-word pages", async ({ page }) => {
  await setup(page);
  for (const [from, to] of [
    ["/bench", "/results"],
    ["/steer?id=steer_1", "/factory?id=steer_1"],
    ["/status", "/models"],
  ]) {
    await page.goto(from!);
    await expect(page).toHaveURL(new RegExp(`${to!.replace("?", "\\?")}$`));
  }
});

test("factory is read-only without an admin token, and unlocks with one", async ({ page }) => {
  await setup(page);
  await page.goto("/factory?id=steer_1");
  await expect(page.getByRole("list", { name: /Review queue \(read-only\)/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Plan and build" })).toHaveCount(0);
  await page.getByLabel("Admin token").fill("secret");
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.getByRole("listbox", { name: /Approval queue/ })).toBeVisible();
});

test("workspace shows the agent log, focus, progress lines, citations and new artifacts", async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto("/jobs/job_demo_1");
  await expect(page.getByRole("status", { name: /Verified/ })).toBeVisible();
  const progress = page.getByRole("list", { name: "Progress per iteration" });
  await expect(progress).toContainText("Hausdorff 0.71→0.31 mm");
  await page.getByRole("tab", { name: /Agent/ }).click();
  const log = page.getByRole("list", { name: "Agent log" });
  await expect(log).toContainText("lengthen it before touching the holes");
  await expect(log).toContainText("set_param");
  await expect(log).toContainText("length 38.00 → 40.10 mm");
  await log.getByRole("button", { name: "Show" }).click();
  await expect(page.getByText(/Agent is looking at: hole_1/)).toBeVisible();
  await expect(page.getByRole("link", { name: /Source 1: Bracket datasheet/ }).first()).toBeAttached();
  await page.getByRole("tab", { name: "Residuals" }).click();
  await expect(page.getByText("Functional probes (advisory)")).toBeVisible();
  await expect(page.getByText("code gate: accepted")).toBeVisible();
  await expect(page.getByRole("region", { name: "Orbit preview" })).toBeVisible();
  await page.getByRole("button", { name: "Export" }).click();
  await expect(page.getByRole("menuitem", { name: /Everything \(\.zip\)/ })).toBeVisible();
  expect(realErrors(errors)).toEqual([]);
});

test("export gate: best effort needs an acknowledgement; publish asks before sending ack", async ({ page }) => {
  const { log } = await setup(page);
  await page.goto("/jobs/job_best");
  await page.getByRole("button", { name: "Export" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Not verified — export is locked");
  await expect(dialog).toContainText("0.83 mm off the photo");
  await expect(dialog.getByRole("link", { name: /fit-test coupon/ })).toBeVisible();
  await dialog.getByLabel(/I understand this part is not verified/).click();
  await expect(page.getByRole("menuitem", { name: /STL/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Best effort, not verified" })).toBeVisible();
  await page.getByRole("button", { name: "I understand, publish as best effort" }).click();
  await expect.poll(() => log.filter((l) => l.startsWith("POST /jobs/job_best/publish")).length).toBe(2);
});

test("fix: tap-to-point taps and the orbit slot go out with the job", async ({ page }) => {
  await setup(page);
  const bodies: string[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/jobs/fix") && r.method() === "POST") bodies.push(r.postData() ?? "");
  });
  await page.goto("/fix");
  // the optional inputs sit behind one disclosure
  await expect(page.getByText("Walk around it (video)")).toBeHidden();
  await page.getByRole("button", { name: /Add more \(optional\)/ }).click();
  await expect(page.getByText("Walk around it (video)")).toBeVisible();
  await page.getByLabel("Upload Top view photo").setInputFiles(join(__dirname, "fixtures/generated/photo.png"));
  await expect(page.getByText("Capture gate passed").first()).toBeVisible();
  await page.getByRole("radio", { name: "Slot" }).click();
  const layer = page.getByRole("group", { name: /tap to mark features/ });
  const box = (await layer.boundingBox())!;
  await layer.click({ position: { x: box.width / 2, y: box.height / 2 } });
  await expect(page.getByRole("button", { name: /Remove point 1 \(slot\)/ })).toBeVisible();
  await page.getByRole("button", { name: "Start the fix" }).click();
  await expect(page).toHaveURL(/\/jobs\/job_demo_1$/);
  expect(bodies[0]).toContain('name="points"');
  expect(bodies[0]).toMatch(/"kind":"slot"/);
});

test("fix: a photo plus a walk-around clip attach without a page error and the voice-note slot appears", async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto("/fix");
  // the optional inputs sit behind one disclosure
  await expect(page.getByText("Walk around it (video)")).toBeHidden();
  await page.getByRole("button", { name: /Add more \(optional\)/ }).click();
  await expect(page.getByText("Walk around it (video)")).toBeVisible();
  await page.getByLabel("Upload Top view photo").setInputFiles(join(__dirname, "fixtures/generated/photo.png"));
  await expect(page.getByText("Capture gate passed").first()).toBeVisible();
  const clip = join(__dirname, "../../../data/synthetic/samples/demo-l-bracket/orbit.mp4");
  await page.locator('input[type=file][accept^="video/"]').first().setInputFiles(clip);
  await expect(page.locator("video").first()).toBeVisible();
  await expect(page.getByText("Voice note about the clip")).toBeVisible();
  await page.waitForTimeout(1500);
  await expect(page.getByText("Something broke on this page")).toHaveCount(0);
  expect(realErrors(errors)).toEqual([]);
});

test("Hinglish toggle translates /fix and is remembered", async ({ page }) => {
  await setup(page);
  await page.goto("/fix");
  await page.getByRole("radio", { name: "Hinglish" }).first().click();
  await expect(page.getByRole("heading", { name: "Photo se verified part tak" })).toBeVisible();
  await expect(page.locator("[lang='hi-Latn']").first()).toBeAttached();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Photo se verified part tak" })).toBeVisible();
});

test("two-device flow: QR on /fix, and the laptop fit page flips when the phone's check arrives", async ({ page }) => {
  await setup(page, { liveFitCheck: true });
  await page.goto("/fix");
  // The e2e server is local-only, so the QR (which a phone could never open) is replaced by a note.
  await expect(page.getByTestId("phone-qr-local")).toContainText("Local server");
  await expect(page.getByRole("img", { name: /QR code: http.*\/fix/ })).toHaveCount(0);
  await page.goto("/jobs/job_demo_1/fit");
  await expect(page.getByText("Lay the part exactly on the pink outline")).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Fit check result" })).toContainText("It fits the outline", { timeout: 10_000 });
  await expect(page.getByRole("dialog", { name: "Fit check result" })).toContainText("0.38");
});

test("part page: fit presets change only internal-fit knobs; share and embed are offered", async ({ page }) => {
  await setup(page);
  await page.goto("/parts/l-bracket");
  await page.getByLabel("Material").selectOption("PLA");
  await expect(page.getByText(/\+0\.20 mm clearance/)).toBeVisible();
  await page.getByRole("button", { name: "Apply to knobs" }).click();
  await expect(page.getByText("Applied")).toBeVisible();
  await page.context().route("https://wa.me/**", (r) => r.fulfill({ status: 200, body: "" }));
  const [popup] = await Promise.all([page.waitForEvent("popup"), page.getByRole("button", { name: "WhatsApp" }).click()]);
  expect(popup.url()).toMatch(/^https:\/\/wa\.me\/\?text=.*parts%2Fl-bracket/);
  await popup.close();
  await page.getByRole("tab", { name: "Embed" }).click();
  await expect(page.getByText(/<iframe src=".*\/embed\/parts\/l-bracket"/)).toBeVisible();
});

test("requests: voting uses the vote endpoint", async ({ page }) => {
  const { log } = await setup(page);
  await page.goto("/requests");
  await page.getByRole("button", { name: /Vote for: Usha cooler wheel/ }).click();
  await expect.poll(() => log.some((l) => l.startsWith("POST /needs/need_1/vote"))).toBeTruthy();
});

test("repair shop: batches are admin-only; a batch shows rows and the price estimate", async ({ page }) => {
  await setup(page);
  await page.goto("/shop");
  await expect(page.getByLabel("Admin token")).toBeVisible();
  await asAdmin(page);
  await page.goto("/shop?batch=b_1");
  const table = page.getByRole("region", { name: "Batch jobs" });
  await expect(table).toContainText("Asha");
  await expect(table).toContainText("₹19");
  await expect(page.getByRole("button", { name: /Job sheet \(PDF\)/ })).toBeEnabled();
});
