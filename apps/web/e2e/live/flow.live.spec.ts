/**
 * Live end-to-end against a running backend (not part of the default run): `pnpm e2e:live`.
 * Needs the API on :8000 (seeded registry) and the web app on LIVE_WEB_URL (default http://localhost:3000).
 */
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { KNOWN_TRANSIENT, watchErrors } from "./watch";

const here = dirname(fileURLToPath(import.meta.url));
const SAMPLE = process.env.LIVE_SAMPLE ?? "demo-spacer";

const watch = watchErrors;

async function noContractErrors(page: Page) {
  await expect(page.getByText(/unexpected shape|did not match the API contract/i)).toHaveCount(0);
}

test.describe.configure({ mode: "serial" });

test("demo job → live workspace → verdict → knob re-bake → export", async ({ page, request }) => {
  const errors = watch(page);
  await page.goto("/jobs/demo");
  await page.getByRole("radio", { name: new RegExp(SAMPLE) }).click();
  await page.getByRole("button", { name: "Run this sample" }).click();
  await page.waitForURL(/\/jobs\/j_[^/]+$/, { timeout: 30_000 });
  const jobId = page.url().split("/").pop()!;

  // Stream to done: the verdict comes only from the verifier's record.
  await expect(page.getByRole("status", { name: /^(Verified|Best effort|Failed)/ })).toBeVisible({ timeout: 180_000 });
  await expect(page.locator("canvas").first()).toBeVisible();
  await noContractErrors(page);

  // Knob re-bake (job program before publish, or the registry part once published).
  const slider = page.getByRole("slider").filter({ hasNot: page.locator("[aria-label='Section position']") }).first();
  await slider.focus();
  const bake = page.waitForResponse((r) => /\/(jobs\/[^/]+|parts\/[^/]+)\/bake\?/.test(r.url()) && r.request().method() === "GET", { timeout: 60_000 });
  await page.keyboard.press("ArrowRight");
  const res = await bake;
  expect(res.status()).toBe(200);
  await expect(page.getByText(/(baked|cache hit) · /)).toBeVisible({ timeout: 60_000 });

  // Export: every listed download resolves.
  await page.getByRole("button", { name: "Export" }).click();
  const links = page.getByRole("menuitem").locator("xpath=self::a");
  const hrefs = await links.evaluateAll((els) => els.map((e) => (e as HTMLAnchorElement).getAttribute("href") ?? ""));
  expect(hrefs.length).toBeGreaterThan(2);
  for (const h of hrefs) {
    const r = await request.get(h);
    expect(r.status(), h).toBe(200);
    expect((await r.body()).length, h).toBeGreaterThan(0);
  }
  await page.keyboard.press("Escape");
  expect(errors, errors.join("\n")).toEqual([]);
  test.info().annotations.push({ type: "job", description: jobId });
});

const PAGES = ["/", "/fix", "/jobs", "/jobs/demo", "/parts", "/models", "/results", "/agents", "/judges", "/factory", "/calibrate", "/requests", "/lessons", "/shop"];
const CONFIGS = [
  { name: "desktop-light", viewport: { width: 1440, height: 900 }, colorScheme: "light" as const, isMobile: false, deviceScaleFactor: 1 },
  { name: "desktop-dark", viewport: { width: 1440, height: 900 }, colorScheme: "dark" as const, isMobile: false, deviceScaleFactor: 1 },
  { name: "mobile-light", viewport: { width: 390, height: 844 }, colorScheme: "light" as const, isMobile: true, deviceScaleFactor: 2 },
  { name: "mobile-dark", viewport: { width: 390, height: 844 }, colorScheme: "dark" as const, isMobile: true, deviceScaleFactor: 2 },
];

test("every page renders real data without contract or console errors (screenshots)", async ({ browser, request }) => {
  const parts = (await (await request.get("/api/v1/parts?limit=1&sort=relevance")).json()) as { items: { slug: string }[] };
  const jobs = (await (await request.get("/api/v1/jobs?limit=5")).json()) as { id: string; status: string }[];
  const extra = [
    ...(parts.items[0] ? [`/parts/${parts.items[0].slug}`] : []),
    ...(jobs.find((j) => j.status === "done") ? [`/jobs/${jobs.find((j) => j.status === "done")!.id}`] : []),
  ];
  for (const cfg of CONFIGS) {
    const ctx = await browser.newContext({ viewport: cfg.viewport, colorScheme: cfg.colorScheme, isMobile: cfg.isMobile, hasTouch: cfg.isMobile, deviceScaleFactor: cfg.deviceScaleFactor });
    const page = await ctx.newPage();
    const errors: string[] = [];
    let current = "";
    page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(`${current}: ${m.text()}`));
    page.on("response", (r) => {
      if (r.status() >= 500 && !KNOWN_TRANSIENT(r.request().method(), r.url())) errors.push(`${current}: ${r.status()} ${r.url()}`);
      // Known backend issue (see report): /bench failure overlays point at blobs this server does not have.
      if (r.status() === 404 && !(current === "/results" && /\/blobs\//.test(r.url()))) errors.push(`${current}: 404 ${r.url()}`);
    });
    page.on("pageerror", (e) => errors.push(`${current}: pageerror: ${e.message}`));
    const dir = join(here, "..", "screenshots", `live-${cfg.name}`);
    mkdirSync(dir, { recursive: true });
    for (const path of [...PAGES, ...extra]) {
      current = path;
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(900);
      await noContractErrors(page);
      const overflow = await page.evaluate((w) => document.documentElement.scrollWidth - w, cfg.viewport.width);
      expect(overflow, `${cfg.name} ${path} horizontal scroll`).toBeLessThanOrEqual(0);
      const name = path === "/" ? "home" : path.slice(1).replace(/\//g, "_");
      await page.screenshot({ path: join(dir, `${name}.png`), fullPage: true, animations: "disabled" });
    }
    expect(errors, `${cfg.name}:\n${errors.join("\n")}`).toEqual([]);
    await ctx.close();
  }
});

test("llms.txt and prompt.txt are proxied from the API", async ({ request }) => {
  const l = await request.get("/llms.txt");
  expect(l.headers()["x-partsmith-source"]).toBe("api");
  expect(await l.text()).toContain("# PartSmith");
  const p = await request.get("/prompt.txt");
  expect(p.headers()["x-partsmith-source"]).toBe("api");
});
