import { expect, test, type Page } from "@playwright/test";
import { asAdmin, expectAccessible, realErrors, setup, shot } from "./helpers";

const functional = (name: string) => name === "desktop-light";

async function noSidewaysScroll(page: Page) {
  const vw = page.viewportSize()!.width;
  expect(await page.evaluate((w) => document.documentElement.scrollWidth - w, vw), "no horizontal page scroll").toBeLessThanOrEqual(0);
}

const TABS = ["overview", "parts", "rules", "audit", "demand"] as const;

for (const tab of TABS) {
  test(`admin ${tab} tab renders, is accessible, has no sideways scroll and no console errors`, async ({ page }, info) => {
    await asAdmin(page);
    const { errors } = await setup(page);
    await page.goto(tab === "overview" ? "/admin" : `/admin?tab=${tab}`);
    await expect(page.getByRole("heading", { name: "Admin", level: 1 })).toBeVisible();
    await expect(page.getByRole("tab", { name: tab[0]!.toUpperCase() + tab.slice(1) })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tabpanel")).toBeVisible();
    await expect(page.getByRole("tabpanel").locator(".skeleton")).toHaveCount(0);
    await page.waitForLoadState("networkidle");
    await noSidewaysScroll(page);
    await shot(page, info, `admin-${tab}`);
    await expectAccessible(page);
    expect(realErrors(errors)).toEqual([]);
  });
}

test("without a token the console asks for one and shows no numbers", async ({ page }) => {
  const { errors, log } = await setup(page);
  await page.route("**/api/v1/status", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ admin: "token", providers: [], warnings: [], mode: "mock" }) }));
  await page.goto("/admin");
  await expect(page.getByRole("textbox", { name: "Admin token" })).toBeVisible();
  await expect(page.getByText("Pass rate")).toHaveCount(0);
  expect(log.some((l) => l.includes("/admin/overview"))).toBe(false);
  await expectAccessible(page);
  expect(realErrors(errors)).toEqual([]);
});

test.describe("functional", () => {
  test.beforeEach(({}, info) => {
    test.skip(!functional(info.project.name), "functional flows run once");
  });

  test("overview numbers come from the API, with n, sources and the spend bar", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    await page.goto("/admin");
    const panel = page.getByRole("tabpanel");
    await expect(panel.getByText("80.0%")).toBeVisible();
    await expect(panel.getByText("4 verified of 5 finished · 6 fix jobs. Counts jobs run on this server, not the bench's fixed test photos on /results.")).toBeVisible();
    // one word for recorded runs in both blocks
    await expect(panel.getByText(/Job numbers leave out the 3 recorded runs \(replays\); the review queue lists them, counted apart\./)).toBeVisible();
    await expect(panel.getByText(/0 of the waiting are recorded runs \(replays\)/)).toBeVisible();
    await expect(panel.getByText("p90 0.62 mm · n = 5")).toBeVisible();
    await expect(panel.getByText("Providers: mock")).toBeVisible();
    await expect(panel.getByRole("meter", { name: "Spent against the daily cap" })).toHaveAttribute("aria-valuenow", "25");
    await expect(panel.getByText("$1.25 of $5.00 spent today (2026-10-31 UTC).")).toBeVisible();
    await expect(panel.getByText("hole too far from the edge")).toBeVisible();
    await expect(panel.getByText(/1 from test reviews, kept apart/)).toBeVisible();
    await expect(panel.getByText(/^From e2e fixture/).first()).toBeVisible();
  });

  test("tabs change ?tab= in the URL", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    await page.goto("/admin");
    await page.getByRole("tab", { name: "Rules" }).click();
    await expect(page).toHaveURL(/\/admin\?tab=rules$/);
    await page.getByRole("tab", { name: "Overview" }).click();
    await expect(page).toHaveURL(/\/admin$/);
  });

  test("withdrawing a part asks for a reason and sends it", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    const posts: { url: string; body: unknown }[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().includes("/admin/")) posts.push({ url: new URL(r.url()).pathname, body: JSON.parse(r.postData() ?? "{}") });
    });
    await page.goto("/admin?tab=parts");
    await expect(page.getByText("4 of 5 checks met")).toBeVisible();
    await expect(page.getByText("0.83 mm (limit 0.50 mm)")).toBeVisible();
    await expect(page.getByText(/Withdrawn .* by admin token: “duplicate of l-bracket”/)).toBeVisible();
    await page.getByRole("button", { name: "Withdraw" }).first().click();
    const confirm = page.getByRole("button", { name: "Withdraw", exact: true }).last();
    await expect(confirm).toBeDisabled();
    await page.getByLabel(/Why take it out of search/).fill("wrong licence");
    await confirm.click();
    await expect.poll(() => posts).toEqual([{ url: "/api/v1/admin/parts/l-bracket/unpublish", body: { reason: "wrong licence" } }]);
  });

  test("switching a rule back on sends its id (slashes encoded) and a reason", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    const posts: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().includes("/admin/rules/")) posts.push(new URL(r.url()).pathname);
    });
    await page.goto("/admin?tab=rules");
    await expect(page.getByText("Given to 2 jobs; later reviews: 1 accepted, 1 sent back, 0 rejected.")).toBeVisible();
    await expect(page.getByText(/Switched off .* “made fits worse”/)).toBeVisible();
    await page.getByRole("button", { name: "Switch on" }).click();
    await page.getByLabel("Why switch it back on?").fill("try again");
    await page.getByRole("button", { name: "Switch on" }).click();
    await expect.poll(() => posts).toEqual(["/api/v1/admin/rules/job_rev_1%2F1%2Fpin1/enable"]);
  });

  test("audit filter asks the API for one action; demand shows requests and the missed searches from /demand", async ({ page }) => {
    await asAdmin(page);
    const { log } = await setup(page);
    await page.goto("/admin?tab=audit");
    await expect(page.getByText("Showing 2 of 2")).toBeVisible();
    await page.getByLabel("Action").selectOption("rule.disable");
    await expect(page.getByText("Showing 1 of 1")).toBeVisible();
    expect(log.some((l) => l.includes("/admin/audit?") && l.includes("action=rule.disable"))).toBe(true);
    await page.getByRole("tab", { name: "Demand" }).click();
    await expect(page.getByText("Usha cooler wheel, 32 mm")).toBeVisible();
    await expect(page.getByText("zeppelin gondola")).toBeVisible();
    await expect(page.getByText(/3× · best match 0%/)).toBeVisible();
    expect(log.some((l) => l.startsWith("GET /demand"))).toBe(true);
  });

  test("the footer links to the console", async ({ page }) => {
    await setup(page);
    await page.goto("/admin");
    await expect(page.getByRole("contentinfo").getByRole("link", { name: "Admin", exact: true })).toHaveAttribute("href", "/admin");
  });
});
