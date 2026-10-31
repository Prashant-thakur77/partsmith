import { expect, test, type Page } from "@playwright/test";
import { expectAccessible, realErrors, setup } from "./helpers";

/** Scroll through the whole page so every section reveals and its lazy parts mount, then return to the top. */
async function revealAll(page: Page) {
  const h = await page.evaluate(() => document.documentElement.scrollHeight);
  for (let y = 0; y < h; y += 500) {
    await page.evaluate((y) => window.scrollTo(0, y), y);
    await page.waitForTimeout(60);
  }
  await page.waitForTimeout(500);
  await page.evaluate(() => window.scrollTo(0, 0));
}

const SHEETS = [
  "Measured, not claimed.",
  "Five steps, from a photo to a checked part.",
  "Watch it fix itself.",
  "A lying model, caught.",
  "Every part is a program.",
  "Buy it, or print it?",
  "A person signs off.",
  "Your coding agent can use it too.",
];

test("every landing sheet renders with numbers read from the API", async ({ page }, info) => {
  test.skip(!info.project.name.endsWith("-light"), "content check, light themes");
  const { errors, log } = await setup(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("A broken plastic part in");
  // hero: four calls to action, the ticker and Fig. 1 drawn from the stored run
  for (const [name, href] of [["Fix a broken part", "/fix"], ["Try a sample", "/jobs/demo"], ["Describe a part", "/describe"], ["Playground", "/playground"]] as const) {
    await expect(page.getByRole("main").getByRole("link", { name, exact: true }).first()).toHaveAttribute("href", href);
  }
  const ticker = page.getByRole("list", { name: "Numbers from this server" });
  await expect(ticker).toContainText("12"); // stats.jobs from the fixture
  await expect(page.getByRole("img", { name: /^Fig\. 1, L-bracket measured on the screen mat: 40\.12 mm by 19\.94 mm.*max error 0\.31 mm against a 0\.50 mm limit\. Recorded run\.$/ })).toBeVisible();
  await revealAll(page);
  for (const title of SHEETS) await expect(page.getByRole("heading", { level: 2, name: title })).toBeVisible();
  // proof strip: bench headline as eval wrote it, and the lying-model suite
  const proof = page.locator("#proof");
  await expect(proof.getByText("0.12 mm", { exact: true }).first()).toBeAttached();
  await expect(proof.getByText("17/17", { exact: true }).first()).toBeAttached();
  // the review chain and the feedback log, scripted rounds labelled
  const review = page.locator("#review");
  await expect(review.getByRole("list", { name: "Review rounds" }).getByRole("listitem")).toHaveCount(2);
  await expect(review.getByText("0.83 mm", { exact: true }).first()).toBeAttached();
  await expect(review.getByText("this corner was square").first()).toBeVisible();
  await expect(review.getByRole("link", { name: /review desk/ })).toHaveAttribute("href", "/review");
  await expect(review.getByRole("link", { name: "Feedback log" })).toHaveAttribute("href", "/review/log");
  // buy or print: a cited price with its link, and the print estimate
  const buy = page.locator("#buy");
  await expect(buy.getByRole("link", { name: /example\.com/ })).toHaveAttribute("href", "https://example.com/parts/lb-40");
  await expect(buy.getByText("6.35", { exact: true }).first()).toBeAttached();
  await expect(buy.getByText("recorded run").first()).toBeVisible();
  // agents: the terminal runs a real registry search and the card drops in
  const agents = page.locator("#agents");
  await agents.scrollIntoViewIfNeeded();
  await expect(agents.getByRole("link", { name: /L-bracket/ })).toHaveAttribute("href", "/parts/l-bracket");
  expect(log.some((l) => l.startsWith("GET /review/job_rev_2"))).toBeTruthy();
  expect(log.some((l) => l.startsWith("GET /jobs/job_replay_1/buy-or-print"))).toBeTruthy();
  expect(realErrors(errors)).toEqual([]);
});

test("landing is accessible in every theme once all sheets have revealed, with no sideways scroll", async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto("/");
  await expect(page.getByRole("img", { name: /^Fig\. 1, L-bracket/ })).toBeVisible();
  await revealAll(page);
  await page.waitForLoadState("networkidle");
  const vw = page.viewportSize()!.width;
  expect(await page.evaluate((w) => document.documentElement.scrollWidth - w, vw), "no horizontal page scroll").toBeLessThanOrEqual(0);
  await expectAccessible(page);
  expect(realErrors(errors)).toEqual([]);
});

test("reduced motion: final values at once, no count-ups, no autoplay, no ghost cursor", async ({ page }, info) => {
  test.skip(!info.project.name.startsWith("desktop-light") && !info.project.name.startsWith("mobile-light"), "behaviour check, light themes");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await setup(page);
  await page.goto("/");
  const fig = page.getByRole("img", { name: /^Fig\. 1, L-bracket/ });
  await expect(fig).toBeVisible();
  // the drawing's labels are the final values straight away, and the stamp has landed
  await expect(fig.locator("text").filter({ hasText: "40.12 mm" })).toHaveCount(1);
  await expect(page.locator("figure").getByText("verified", { exact: true }).first()).toBeVisible();
  // counters print the real value immediately when scrolled to (never a zero on the way)
  await page.locator("#proof").scrollIntoViewIfNeeded();
  await expect(page.locator("#proof [aria-hidden]").filter({ hasText: /^0\.12 mm$/ }).first()).toBeAttached();
  await expect(page.locator("#proof").getByText(/^0\.00 mm$/)).toHaveCount(0);
  // the replay does not autoplay (no pause button), and the knob demo never moves on its own
  await page.locator("#loop").scrollIntoViewIfNeeded();
  await expect(page.locator("#loop").getByRole("button", { name: "Next step" })).toBeVisible();
  await expect(page.locator("#loop").getByRole("button", { name: /Pause replay|Play replay/ })).toHaveCount(0);
  await page.locator("#program").scrollIntoViewIfNeeded();
  await expect(page.getByRole("slider", { name: "Base leg length" })).toBeVisible();
  await page.waitForTimeout(4800);
  await expect(page.getByText("demo drag")).toHaveCount(0);
  await expect(page.getByRole("slider", { name: "Base leg length" })).toHaveValue("40");
});
