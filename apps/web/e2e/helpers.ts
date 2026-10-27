import { fileURLToPath as __f2p } from "node:url";
import { dirname as __dn } from "node:path";
const __dirname = __dn(__f2p(import.meta.url));
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, type TestInfo } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { CALIBRATION, mockApi, type MockOptions } from "./fixtures/api";

/** Mock the API, seed a screen calibration that matches this browser, and collect console errors. */
export async function setup(page: Page, opts: MockOptions & { calibrated?: boolean } = {}) {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`${m.text()} @ ${m.location().url}`);
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  if (opts.calibrated !== false) {
    await page.addInitScript((cal) => {
      const c = { ...cal, dpr: window.devicePixelRatio, screen_w: window.screen.width, screen_h: window.screen.height };
      window.localStorage.setItem("partsmith.screen-calibration.v1", JSON.stringify(c));
    }, CALIBRATION);
  }
  const log = await mockApi(page, opts);
  return { errors, log };
}

export async function shot(page: Page, info: TestInfo, name: string, fullPage = true) {
  const dir = join(__dirname, "screenshots", info.project.name);
  mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(dir, `${name}.png`), fullPage, animations: "disabled" });
}

export async function expectAccessible(page: Page) {
  const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]).analyze();
  // Serious/critical fail everywhere; heading order and landmark structure are enforced too (screen-reader navigation).
  const STRUCTURE = new Set(["heading-order", "landmark-one-main", "landmark-unique", "region", "page-has-heading-one", "landmark-no-duplicate-banner", "landmark-no-duplicate-contentinfo"]);
  const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical" || STRUCTURE.has(v.id));
  const summary = bad.map((v) => `${v.impact} ${v.id}: ${v.help}\n  ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join("\n  ")}`).join("\n");
  expect(bad, summary).toEqual([]);
}

/** Console errors that are not ours: none are expected with the API mocked. */
export function realErrors(errors: string[]): string[] {
  return errors.filter((e) => !/Download the React DevTools|GPU stall|WebGL: INVALID|swiftshader/i.test(e));
}
