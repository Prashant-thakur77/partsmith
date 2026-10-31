import { expect, test, type Page } from "@playwright/test";
import { jobDetail, partCards, reviewQueue } from "./fixtures/api";
import { asAdmin, expectAccessible, realErrors, setup } from "./helpers";

const desktop = (name: string) => name.startsWith("desktop");
const LATCH = "Cupboard turn-button latch — broken (synthetic, paper)";

/** Three finished attempts at the same part, plus one other job (the list API, newest first). */
async function repeatedJobs(page: Page) {
  const s = jobDetail.summary;
  const list = [
    { ...s, id: "job_a", title: LATCH, verified: false, max_error_mm: 4.32 },
    { ...s, id: "job_b", title: "Spacer (synthetic, clean)", verified: true, max_error_mm: 0.08 },
    { ...s, id: "job_c", title: LATCH, verified: false, max_error_mm: 8.57 },
    { ...s, id: "job_e", title: LATCH, verified: false, max_error_mm: 20.35 },
  ];
  await page.route(/\/api\/v1\/jobs(\?.*)?$/, (route) => (route.request().method() === "GET" ? route.fulfill({ json: list }) : route.fallback()));
}

test.describe("at a glance", () => {
  test.beforeEach(({}, info) => {
    test.skip(info.project.name !== "desktop-light" && info.project.name !== "mobile-light", "functional checks run in light mode");
  });

  test("jobs: same-title runs fold under the best one; the summary still counts every run", async ({ page }) => {
    const { errors } = await setup(page);
    await repeatedJobs(page);
    await page.goto("/jobs");
    await expect(page.getByTestId("jobs-summary")).toContainText("1 of 4 listed verified");
    const jobs = page.getByRole("list", { name: "Jobs" });
    await expect(page.getByTestId("job-group")).toHaveCount(2);
    const latch = page.getByTestId("job-group").first();
    await expect(latch.getByTestId("job-row")).toHaveCount(1);
    await expect(latch.getByTestId("job-row").first()).toHaveAttribute("href", "/jobs/job_a"); // the best attempt (4.32 mm) leads
    const more = latch.getByRole("button", { name: /\+2 more attempts at the same part/ });
    await expect(more).toHaveAttribute("aria-expanded", "false");
    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "true");
    await expect(jobs.getByRole("list", { name: /^Other attempts/ }).getByTestId("job-row")).toHaveCount(2);
    await expectAccessible(page);
    expect(realErrors(errors)).toEqual([]);
  });

  test("review queue: repeated attempts fold, and list under the best one while it is selected", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    const base = reviewQueue.items[0]!;
    const items = [
      { ...base, job_id: "job_rev_2", title: LATCH, verdict: { status: "best_effort", max_error_mm: 8.57 } },
      { ...base, job_id: "job_rev_x", title: LATCH, verdict: { status: "best_effort", max_error_mm: 4.32 } },
      { ...base, job_id: "job_rev_y", title: LATCH, verdict: { status: "best_effort", max_error_mm: 20.35 } },
      reviewQueue.items[1]!,
    ];
    await page.route(/\/api\/v1\/review\/queue(\?.*)?$/, (route) => route.fulfill({ json: { items } }));
    await page.goto("/review?job=job_demo_1");
    const queue = page.getByRole("listbox", { name: /Review queue/ });
    await expect(queue.getByRole("option")).toHaveCount(2);
    await expect(queue.getByTestId("queue-more")).toContainText("+2 more attempts at the same part");
    await queue.getByRole("option").first().click();
    await expect(page).toHaveURL(/job=job_rev_x/); // the best attempt leads the group
    await expect(queue.getByRole("option")).toHaveCount(4);
  });

  test("results: the size-pass column is named for what it checks and explained next to Verified", async ({ page }) => {
    await setup(page);
    await page.goto("/results");
    await expect(page.getByRole("columnheader", { name: "All sizes within 0.5 mm of truth" }).first()).toBeAttached();
    await expect(page.getByTestId("pass-vs-verified").first()).toContainText("it also needs the outline to match the photo and the part tests to pass");
  });

  test("parts: a best-effort card under the size limit leads with the failing check, the millimetres second", async ({ page }) => {
    await setup(page);
    const card = { ...partCards[2]!, slug: "control-knob", title: "Control knob", max_error_mm: 0.498, status_reason: "the side view's average edge gap is 0.20 mm (needs ≤ 0.15 mm)" };
    await page.route(/\/api\/v1\/parts(\?.*)?$/, (route) => route.fulfill({ json: { items: [card, partCards[0]], next_cursor: null, total: 2, coverage: null, match: "all", hint: null } }));
    await page.goto("/parts");
    const link = page.getByRole("link", { name: /Control knob/ });
    await expect(link).toContainText("Best effort · side outline");
    await expect(link.getByTestId("card-max-gap")).toHaveText("max gap 0.498 mm");
  });

  test("job page: a card offers the fit check and a labelled example", async ({ page }) => {
    await setup(page);
    await page.goto("/jobs/job_demo_1");
    const card = page.getByTestId("fit-check-card");
    await expect(card).toBeVisible();
    await expect(card.getByRole("link", { name: /Open the fit check/ })).toHaveAttribute("href", "/jobs/job_demo_1/fit");
    await card.getByRole("link", { name: /See an example/ }).click();
    await expect(page).toHaveURL(/\/jobs\/job_demo_1\/fit\?example=1/);
    await expect(page.getByTestId("fit-example-note")).toContainText("Nothing on this page is measured");
  });

  test("fit check without calibration links to the labelled example", async ({ page }) => {
    await setup(page, { calibrated: false });
    await page.goto("/jobs/job_demo_1/fit");
    await expect(page.getByRole("heading", { name: "Calibrate this screen first" })).toBeVisible();
    await page.getByRole("link", { name: /See a labelled example first/ }).click();
    await expect(page.getByRole("img", { name: /^Example: the model outline with 2 holes and its sizes 40\.00 mm/ })).toBeVisible();
  });
});

test("review at 1440 × 900: the decision bar never covers the photo, the model or the caption", async ({ page }, info) => {
  test.skip(!desktop(info.project.name), "the bar sticks from tablet width");
  await asAdmin(page);
  await setup(page);
  await page.goto("/review?job=job_demo_1");
  const bar = page.getByRole("region", { name: "Your decision" });
  const photo = page.getByRole("region", { name: "Should look like" });
  const model = page.getByRole("region", { name: "Agent made" });
  await expect(bar).toBeVisible();
  await expect(photo.getByRole("img", { name: /Rectified top photo/ })).toBeVisible();
  // "covered" = the bar lies over a panel whose top edge is on screen above the bar (the panel's lower part hidden)
  const covered = async () =>
    page.evaluate(() => {
      const r = (sel: string) => document.querySelector(`[aria-label="${sel}"]`)!.getBoundingClientRect();
      const top = document.querySelector("header.sticky")?.getBoundingClientRect().bottom ?? 0;
      const b = r("Your decision");
      const hit = (x: DOMRect) => Math.min(b.bottom, x.bottom) - Math.max(b.top, x.top) > 1 && x.top < b.top - 1 && x.top >= top - 1;
      return { photo: hit(r("Should look like")), model: hit(r("Agent made")) };
    });
  // at load the bar sits above the panels
  const [b, p, m] = await Promise.all([bar.boundingBox(), photo.boundingBox(), model.boundingBox()]);
  expect(b!.y + b!.height).toBeLessThanOrEqual(p!.y + 1);
  expect(b!.y + b!.height).toBeLessThanOrEqual(m!.y + 1);
  // and at no scroll position does it hide the lower part of the photo or the model
  for (let y = 0; y <= 900; y += 150) {
    await page.evaluate((y) => window.scrollTo(0, y), y);
    expect(await covered(), `scrolled to ${y}px`).toEqual({ photo: false, model: false });
  }
});
