import { expect, test, type Page } from "@playwright/test";
import { expectAccessible, realErrors, setup } from "./helpers";
import { lessons as lessonFixture } from "./fixtures/api";

const desktop = (name: string) => name === "desktop-light";
const phone = (name: string) => name === "mobile-light";

async function noSideways(page: Page) {
  const vw = page.viewportSize()!.width;
  expect(await page.evaluate((w) => document.documentElement.scrollWidth - w, vw), "no horizontal page scroll").toBeLessThanOrEqual(0);
}

/** Layout shift summed from first paint (PerformanceObserver, buffered), the way CLS counts it. */
async function trackShifts(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __cls: number };
    w.__cls = 0;
    new PerformanceObserver((l) => {
      for (const e of l.getEntries() as unknown as { value: number; hadRecentInput: boolean }[]) if (!e.hadRecentInput) w.__cls += e.value;
    }).observe({ type: "layout-shift", buffered: true });
  });
}
const cls = (page: Page) => page.evaluate(() => (window as unknown as { __cls: number }).__cls);

test.describe("phone", () => {
  test.beforeEach(({}, info) => test.skip(!phone(info.project.name), "phone layout checks run once"));

  test("fix: the first-visit guide is in the server HTML in both states, so nothing shifts", async ({ page, request }) => {
    const html = await (await request.get("/fix")).text();
    expect(html).toContain("First time? Three steps to a measured part");
    expect(html).toContain("Show the 3-step guide");
    expect(html).toContain("partsmith.fix-guide.dismissed.v1");
    await trackShifts(page);
    const { errors } = await setup(page);
    await page.goto("/fix");
    await expect(page.getByRole("region", { name: "First time? Three steps to a measured part" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Show the 3-step guide" })).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    expect(await cls(page)).toBeLessThan(0.05);
    await page.getByRole("button", { name: "Got it" }).click();
    await page.reload();
    await expect(page.getByRole("button", { name: "Show the 3-step guide" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(await cls(page)).toBeLessThan(0.05);
    await noSideways(page);
    expect(realErrors(errors)).toEqual([]);
  });

  test("review: the agent's model shows a shaded picture before 3D loads; the page passes axe", async ({ page }) => {
    const { errors } = await setup(page);
    await page.goto("/review");
    const made = page.getByRole("region", { name: "Agent made" });
    await made.scrollIntoViewIfNeeded();
    const poster = made.locator('img[src*="/model.png"]');
    await expect(poster).toBeVisible();
    expect(await poster.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    await expect(made.getByRole("button", { name: "View in 3D" })).toBeVisible();
    await noSideways(page);
    await expectAccessible(page);
    expect(realErrors(errors)).toEqual([]);
  });

  test("landing: the tagline keeps each arrow with its word and the title block is not cut off", async ({ page }) => {
    const { errors } = await setup(page);
    await page.goto("/");
    const tagline = page.locator("p", { hasText: /^Photo/ }).first();
    // every arrow sits on the same line as the word after it
    const pairs = await tagline.locator("span.whitespace-nowrap").evaluateAll((els) => els.map((e) => e.getClientRects().length));
    expect(pairs).toEqual([1, 1, 1]);
    const fig = page.locator("figure").first();
    await expect(fig.getByText("Fig. 1 · part").first()).toBeVisible();
    const cut = await fig.locator("dl:visible dd, dl:visible dt").evaluateAll((els) => els.filter((e) => e.scrollWidth > e.clientWidth + 1).map((e) => e.textContent));
    expect(cut, `cut off: ${cut.join(", ")}`).toEqual([]);
    await noSideways(page);
    expect(realErrors(errors)).toEqual([]);
  });
});

test.describe("desktop", () => {
  test.beforeEach(({}, info) => test.skip(!desktop(info.project.name), "functional flows run once"));

  test("fix: on a local server the QR is replaced by a note", async ({ page }) => {
    await setup(page);
    await page.goto("/fix");
    await expect(page.getByTestId("phone-qr-local")).toBeVisible();
    await expect(page.getByRole("img", { name: /^QR code:/ })).toHaveCount(0);
  });

  test("lessons: duplicates share a card per family, long families collapse; nobody is promoted by the page", async ({ page }) => {
    const { errors } = await setup(page);
    const NOW = Date.now() / 1000;
    const dup = (i: number, final: number) => ({
      id: `l_dup_${i}`,
      scope: "cover",
      rule: `battery_cover: corner_radius moved to ${final}`,
      evidence: { template: "battery_cover", param: "corner_radius", first: 1, final },
      status: "candidate",
      promoted_by: null,
      created_at: NOW - i * 60,
      links: [{ kind: "job", id: `job_${i}`, url: "", page: `/jobs/job_${i}` }],
      track: { used_in: 0, accepted: 0, improved: 0, rejected: 0 },
    });
    const solo = (i: number) => ({ ...dup(10 + i, 2), id: `l_solo_${i}`, rule: `cover rule ${i}`, evidence: { template: "battery_cover", param: `knob_${i}` } });
    const list = [...lessonFixture, dup(1, 1.9), dup(2, 2.4), dup(3, 2.1), ...[0, 1, 2, 3, 4].map(solo)];
    await page.route("**/api/v1/lessons", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(list) }));
    await page.goto("/lessons");
    const cover = page.getByRole("region", { name: /^Cover/ });
    await expect(cover.getByRole("heading", { name: /6 cards from 8 suggestions/ })).toBeVisible();
    const card = cover.getByRole("listitem").filter({ hasText: "suggested by 3 runs" });
    await expect(card).toContainText("corner_radius, first build → final: 1 → 1.9 · 1 → 2.4 · 1 → 2.1");
    const cards = cover.locator("ul").first().locator(":scope > li");
    await expect(cards).toHaveCount(3);
    await cover.getByRole("button", { name: "Show all 6" }).click();
    await expect(cards).toHaveCount(6);
    await cover.getByRole("button", { name: "Fold" }).click();
    await expect(cards).toHaveCount(0);
    await expect(page.getByText("None has been used in a job yet")).toBeVisible();
    await expect(page.getByRole("button", { name: "Promote" })).toHaveCount(0);
    await expectAccessible(page);
    expect(realErrors(errors)).toEqual([]);
  });

  test("jobs: a summary computed from the list and filters kept in the URL", async ({ page }) => {
    const { errors } = await setup(page);
    await page.goto("/jobs");
    await expect(page.getByTestId("jobs-summary")).toContainText("1 of 2 verified · median max gap 0.31 mm (1 finished job)");
    await page.getByRole("group", { name: "Filter by result" }).getByRole("button", { name: /Verified/ }).click();
    await expect(page).toHaveURL(/status=verified/);
    await expect(page.getByRole("list", { name: "Jobs" }).getByRole("listitem")).toHaveCount(1);
    await page.goto("/jobs?status=failed");
    await expect(page.getByText("No jobs match these filters")).toBeVisible();
    await page.getByRole("button", { name: "Clear the filters" }).click();
    await expect(page.getByRole("list", { name: "Jobs" }).getByRole("listitem")).toHaveCount(2);
    await expectAccessible(page);
    expect(realErrors(errors)).toEqual([]);
  });

  test("judges: the player starts by itself at 2× and shows the run's pictures", async ({ page }) => {
    const { errors } = await setup(page);
    await page.goto("/judges");
    const player = page.locator("#replay");
    // autoplay waits until the player is in view
    await player.getByRole("radiogroup", { name: "Speed" }).scrollIntoViewIfNeeded();
    await expect(player.getByRole("button", { name: /^(Pause|Replay again)$/ })).toBeVisible();
    await expect(player.getByRole("radio", { name: "2×" })).toHaveAttribute("aria-checked", "true");
    await expect(player.locator("figure img").first()).toBeVisible();
    await expect.poll(async () => Number((await player.getByText(/^\d+\/\d+ events$/).textContent())?.split("/")[0])).toBeGreaterThan(3);
    await expectAccessible(page);
    expect(realErrors(errors)).toEqual([]);
  });

  test("judges: with reduced motion the player opens on the final frame", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const { errors } = await setup(page);
    await page.goto("/judges");
    const player = page.locator("#replay");
    await expect(player.getByRole("button", { name: "Replay again" })).toBeVisible();
    await expect(player.getByText(/^Finished:/)).toBeVisible();
    await expect(player.locator("figure img").first()).toBeVisible();
    expect(realErrors(errors)).toEqual([]);
  });

  test("labs pages with no records explain who they are for and show a labelled example", async ({ page }) => {
    const { errors } = await setup(page);
    await page.route("**/api/v1/steer?*", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
    await page.route("**/api/v1/needs", (r) => (r.request().method() === "GET" ? r.fulfill({ status: 200, contentType: "application/json", body: "[]" }) : r.fallback()));
    await page.goto("/factory");
    await expect(page.getByText("No factory runs on this server yet")).toBeVisible();
    await expect(page.getByRole("region", { name: "What a run looks like" })).toContainText("illustration · not a run");
    await expectAccessible(page);
    await page.goto("/requests");
    await expect(page.getByRole("region", { name: "What a request looks like" })).toContainText("not a real request");
    await page.getByRole("button", { name: "Request a part" }).click();
    await expect(page.getByLabel("What part do you need?")).toBeFocused();
    await expectAccessible(page);
    await page.goto("/shop");
    const ex = page.getByRole("region", { name: "What a batch looks like" });
    await expect(ex).toContainText("recorded runs · placeholder customers");
    await expect(ex.getByRole("region", { name: "Example batch (recorded runs)" })).toContainText("0.31 mm");
    await expectAccessible(page);
    await noSideways(page);
    expect(realErrors(errors)).toEqual([]);
  });

  test("describe: the empty result area shows a labelled template preview that fills the form", async ({ page }) => {
    const { errors } = await setup(page);
    await page.goto("/describe");
    const ex = page.getByRole("region", { name: "What a result looks like" });
    await expect(ex).toContainText("template at its defaults · not built from your text");
    await expect(ex.getByRole("img")).toBeVisible();
    await ex.getByRole("link", { name: "Use this sentence" }).click();
    await expect(page.getByLabel("What do you need? Say the numbers you know.")).toHaveValue("A spacer 12 mm tall for an M3 screw, outer diameter 7 mm");
    await expectAccessible(page);
    expect(realErrors(errors)).toEqual([]);
  });
});
