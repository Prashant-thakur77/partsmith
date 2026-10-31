import { fileURLToPath as __f2p } from "node:url";
import { dirname as __dn } from "node:path";
const __dirname = __dn(__f2p(import.meta.url));
import { expect, test } from "@playwright/test";
import { join } from "node:path";
import { setup } from "./helpers";

// Quick wins: search coverage banner, part data as JSON, download names, the /how comparison, the job cost card,
// sizes the photo can't see on /fix, and material/load notes. TEST DATA (mocked API).

test.beforeEach(({}, info) => {
  test.skip(info.project.name !== "desktop-light" && info.project.name !== "mobile-light", "content checks, light themes");
});

test("a partial search match shows the banner with describe, photo and request actions", async ({ page }) => {
  const { log } = await setup(page);
  await page.goto("/parts?q=bracket%2099%20mm");
  const banner = page.getByTestId("search-match-banner");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("Only a partial match for “bracket 99 mm”");
  await expect(banner).toContainText("best part matches 50 % of your words and sizes");
  await expect(banner.getByRole("link", { name: "Describe it" })).toHaveAttribute("href", "/describe?q=bracket%2099%20mm");
  await expect(banner.getByRole("link", { name: "Fix from a photo" })).toHaveAttribute("href", "/fix");
  await banner.getByRole("button", { name: "Request it" }).click();
  await expect.poll(() => log.some((l) => l.startsWith("POST /needs"))).toBeTruthy();
  await expect(page.getByRole("link", { name: /L-bracket/ }).first()).toBeVisible(); // results still listed
});

test("a good match shows no banner; nothing found links to describe and fix", async ({ page }) => {
  await setup(page);
  await page.goto("/parts?q=bracket");
  await expect(page.getByRole("link", { name: /L-bracket/ }).first()).toBeVisible();
  await expect(page.getByTestId("search-match-banner")).toHaveCount(0);
  await page.goto("/parts?q=zeppelin");
  await expect(page.getByRole("button", { name: "Request this part" })).toBeVisible();
  await expect(page.getByRole("link", { name: "describe it" })).toHaveAttribute("href", "/describe?q=zeppelin");
  await expect(page.getByRole("link", { name: "fix it from a photo" })).toHaveAttribute("href", "/fix");
});

test("part page: download names, the Data tab and the load note", async ({ page }) => {
  await setup(page);
  await page.goto("/parts/l-bracket?thickness=5");
  await expect(page.getByRole("heading", { name: "L-bracket", level: 1 })).toBeVisible();
  const downloads = page.getByRole("group", { name: "Download files" });
  await expect(downloads.getByRole("link", { name: /^STL/ })).toHaveAttribute("download", "partsmith-l-bracket-thickness5.stl");
  await expect(downloads.getByRole("link", { name: /^STEP/ })).toHaveAttribute("download", "partsmith-l-bracket-thickness5.step");
  await page.getByRole("tab", { name: "Data" }).click();
  const data = page.getByRole("tabpanel", { name: "Data" });
  await expect(data.getByRole("link", { name: "verification.json" })).toHaveAttribute("href", "/api/v1/parts/l-bracket/verification.json");
  await expect(data.getByRole("link", { name: "params.json" })).toHaveAttribute("href", "/api/v1/parts/l-bracket/params.json");
  await expect(data.getByText(/curl ".*\/api\/v1\/parts\/l-bracket\/verification\.json"/)).toBeVisible();
  const note = page.getByTestId("load-note").first();
  await expect(note).toContainText("PETG or ASA rather than PLA");
  await expect(note).toContainText("Not for safety-critical loads");
});

test("/how compares kinds of tools in an accessible table that scrolls in its own box", async ({ page }) => {
  await setup(page);
  await page.goto("/how");
  const table = page.getByRole("table");
  await expect(table.getByRole("columnheader")).toHaveText(["Feature", "Text-to-CAD tools", "Photo-to-3D generators", "Phone scanning apps", "Model-site customizers", "PartSmith"]);
  await expect(table.getByRole("rowheader")).toHaveCount(7);
  await expect(table.getByRole("rowheader", { name: "Pass / fail decided by code against your photo" })).toBeVisible();
  const vw = page.viewportSize()!.width;
  expect(await page.evaluate((w) => document.documentElement.scrollWidth - w, vw)).toBeLessThanOrEqual(0);
  // the full axe pass for /how (after every section has revealed) runs in pages.spec.ts
});

test("job page: cost from the job's own model calls, labelled mock", async ({ page }) => {
  await setup(page);
  await page.goto("/jobs/job_demo_1");
  const cost = page.getByTestId("job-cost");
  await expect(cost).toBeVisible();
  await expect(cost).toContainText("mock — no spend");
  await expect(cost.getByRole("table", { name: "Model calls per model" })).toBeVisible();
});

test("fix: sizes the photo can't see go out with the job", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop-light", "one functional run");
  await setup(page);
  const bodies: string[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/jobs/fix") && r.method() === "POST") bodies.push(r.postData() ?? "");
  });
  await page.goto("/fix");
  await page.getByRole("button", { name: "Add a size" }).click(); // hydrated
  await page.getByLabel("Upload Top view photo").setInputFiles(join(__dirname, "fixtures/generated/photo.png"));
  await expect(page.getByRole("listitem").filter({ hasText: "Top photo added" })).toContainText("done");
  await page.getByLabel("Size 1 in millimetres").fill("-2");
  await expect(page.getByText("Type a size in mm (more than 0)")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start the fix" })).toBeDisabled();
  await page.getByLabel("Size 1 in millimetres").fill("8");
  await page.getByRole("button", { name: "Add a size" }).click();
  await page.getByLabel("Which size 2").selectOption("socket_depth");
  await page.getByLabel("Size 2 in millimetres").fill("4,5");
  await page.getByRole("button", { name: "Start the fix" }).click();
  await expect(page).toHaveURL(/\/jobs\/job_demo_1$/);
  expect(bodies[0]).toContain('name="hidden_dims"');
  expect(bodies[0]).toContain('[{"name":"bore_d","value_mm":8},{"name":"socket_depth","value_mm":4.5}]');
});
