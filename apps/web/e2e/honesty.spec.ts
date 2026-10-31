import { expect, test } from "@playwright/test";
import { bench, families, status } from "./fixtures/api";
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
  await expect(ticker).toContainText("strict: every check ≤ 0.5 mm");
  await expect(page.getByText("34 of 40 passed verification (strict: every check ≤ 0.5 mm)")).toBeAttached();
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
  // the failing view line reads in plain words; the alignment line waits behind Details
  await expect(page.getByText(/top view \(photo frame\): overlap \(IoU\) 0\.947 .* outline gap 0\.83 mm/).first()).toBeVisible();
  const refined = page.getByText("top: refined in the photo frame by -0.15 deg, (-3.93, -2.12) mm on the mat").first();
  await expect(refined).toBeHidden();
  await page.getByText("Details (1)").first().click();
  await expect(refined).toBeVisible();
  // values the photo never checked sit in a closed disclosure with their count
  await expect(page.getByText("Not checked against a photo").first()).toBeVisible();
  await expect(page.getByText("arm_width", { exact: true })).toBeHidden();
  // the judge ran as the rule-based mock and saved no scorecard: the panel says so
  await expect(page.getByRole("region", { name: "Judge scorecard" })).toContainText("judge: mock (rule-based)");
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

test("results: shares read as counts of cases, failures by part and condition, and the pass rate says which set it counts", async ({ page }) => {
  await setup(page);
  const withCase = { ...bench, failures: [...bench.failures, { title: "syn-hook-tilt-s656341 · PS (synthetic, held_out)", reason: "worst length -0.56 mm", overlay_url: null }] };
  await page.route("**/api/v1/bench", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(withCase) }));
  await page.goto("/results");
  const table = page.getByRole("region", { name: "Bench table (key columns)" }).first();
  await expect(table).toContainText("9/10 (90%)");
  await expect(table).not.toContainText("0.9");
  await expect(page.getByTestId("pass-rate-note")).toContainText("This 34/40 is the strict pass rate");
  const gallery = page.locator("#failures");
  await expect(gallery.getByText("Wall hook · tilted photo")).toBeVisible();
  await expect(gallery.getByText("syn-hook-tilt-s656341 · full pipeline (synthetic, held-out)")).toBeVisible();
});

test("models: one set of mode words with one legend; the open-weights line says what it counts", async ({ page }) => {
  await setup(page);
  const s = { ...status, open_weights: { open_weights_only: false, stages_live_on_open_weights: [], calls_on_open_weights: 404, last_live_call_ts: {} } };
  await page.route("**/api/v1/status", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(s) }));
  await page.goto("/models");
  await expect(page.getByTestId("mode-legend")).toContainText("recorded");
  await expect(page.getByTestId("open-weights-line")).toHaveText("404 model calls in this server's job log ran live on open-weight models. No stage is set to use them live right now (this server answers in mock mode).");
});

test("agents: copy-paste examples never hold a <slug> placeholder", async ({ page }) => {
  await setup(page);
  await page.goto("/agents");
  const rest = page.locator("#rest");
  await expect(rest).toContainText("/variant?want=12+mm+tall,+for+an+M4+screw");
  await expect(rest).not.toContainText("<slug>");
  // no verified spacer in this registry: the first line stores the top search hit instead
  await expect(rest).toContainText(`SLUG=$(curl -s`);
  await expect(rest).toContainText("/api/v1/parts/$SLUG/bake?height=12&bore_d=4.5&format=stl&download=1");
});

test("parts: a family with no parts gets no filter chip", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/families", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([...families, { family: "hinge", title: "Hinges", count: 0, verified: 0 }]) }),
  );
  await page.goto("/parts");
  const chips = page.getByRole("group", { name: "Families" });
  await expect(chips.getByRole("button", { name: /Brackets/ })).toBeVisible();
  await expect(chips.getByRole("button", { name: /Hinges/ })).toHaveCount(0);
});

test("models and judges: how a stage runs now sits beside the models seen in its logged calls", async ({ page }) => {
  await setup(page);
  await page.goto("/models");
  await expect(page.getByText("Runs now", { exact: true }).first()).toBeVisible(); // header pill (the table column is the other)
  await expect(page.getByTestId("stage-models").getByRole("columnheader", { name: "Runs now" })).toBeVisible();
  const judge = page.getByTestId("stage-models").locator('tr[data-stage="judge"]');
  await expect(judge).toContainText("muse-glimmer-30b-q4_k_m"); // set up now
  await expect(judge.locator("td").nth(1)).toContainText("mock"); // runs now
  await expect(judge).toContainText("muse-spark-1.3");
  await expect(judge).toContainText("in recorded runs");
  await expect(judge).toContainText("A logged call used a different model than the one set up now.");
  await expect(page.getByTestId("stage-models").getByRole("columnheader", { name: /Seen in logged calls/ })).toBeVisible();
  await page.goto("/judges"); // the fixture has six stages: all fit without "Show all"
  await expect(page.getByTestId("stage-models").locator('tr[data-stage="judge"]')).toContainText("muse-spark-1.3");
});

test("admin: an open (dev) server says so in a warning banner", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/status", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...status, admin: "open (dev)" }) }));
  await page.goto("/admin");
  await expect(page.getByTestId("admin-open-warning")).toContainText("Development mode: admin actions are open.");
  await expect(page.getByTestId("admin-open-warning")).toContainText("PARTSMITH_ADMIN_TOKEN");
});

test("admin: a token server shows no dev-mode warning", async ({ page }) => {
  await setup(page);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Admin", level: 1 })).toBeVisible();
  await expect(page.getByTestId("admin-open-warning")).toHaveCount(0);
});

test("how: the real-photo row claims only what the bench shows and links to Accuracy", async ({ page }) => {
  await setup(page);
  await page.goto("/how#compare");
  const row = page.getByRole("row", { name: /Real millimetres from a plain photo/ });
  const ours = row.getByRole("cell").last();
  await expect(ours).toContainText("Partial");
  await expect(ours).not.toContainText("Yes");
  await expect(ours.getByRole("link", { name: "See Accuracy" })).toHaveAttribute("href", /^\/results/);
});

test("describe: the sentence stays on the questions and result screens", async ({ page }) => {
  await setup(page);
  await page.goto("/describe?id=d_261031_0000asks");
  await expect(page.getByTestId("describe-you-asked")).toContainText("You asked");
  await page.goto("/describe?id=d_261031_0000done");
  await expect(page.getByTestId("describe-you-asked")).toBeVisible();
  await expect(page.getByTestId("describe-how-made")).toContainText("How it was made");
  await expect(page.getByTestId("describe-how-made")).toContainText("Photograph the real part");
});
