import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { expectAccessible, realErrors, setup } from "./helpers";

const deck = () => JSON.parse(readFileSync(new URL("../public/deck/data.json", import.meta.url), "utf8"));

test("/how: every step opens with the run's real files, plain words and why it can't be faked", async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto("/how");
  const steps = page.getByRole("region", { name: "The eight steps" });
  const tabs = steps.getByRole("tab");
  await expect(tabs).toHaveCount(8);
  for (let i = 0; i < 8; i++) {
    await tabs.nth(i).click();
    const panel = steps.getByRole("tabpanel");
    await expect(panel.getByText(`Step ${i + 1} of 8`)).toBeVisible();
    await expect(panel.getByText("Why this step can't be faked")).toBeVisible();
    await expect(panel.getByText("recorded run · rendered sample photo")).toBeVisible();
    const pictures = panel.locator("img");
    for (let k = 0; k < (await pictures.count()); k++) {
      await pictures.nth(k).scrollIntoViewIfNeeded();
      await expect.poll(() => pictures.nth(k).evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    }
  }
  await expectAccessible(page);
  expect(realErrors(errors)).toEqual([]);
});

test("/how: the run's numbers come from its data file, and the steps walk by button and by keyboard", async ({ page }) => {
  const { run, bypass } = deck();
  await setup(page);
  await page.goto("/how");
  const steps = page.getByRole("region", { name: "The eight steps" });
  const panel = steps.getByRole("tabpanel");
  await steps.getByRole("tab", { name: "Program" }).click();
  await expect(panel.locator("pre")).toContainText(run.params[0]);
  await steps.getByRole("tab", { name: "Check" }).click();
  await expect(panel).toContainText(`blocked ${bypass.blocked} of ${bypass.attempts} times`);
  await panel.getByRole("button", { name: "Fix" }).click();
  await expect(steps.getByRole("tab", { name: "Fix" })).toHaveAttribute("aria-selected", "true");
  const last = run.rounds_detail.at(-1);
  await expect(panel).toContainText(`Round ${last.round}: ${last.error_mm} mm`);
  await panel.getByRole("button", { name: "Check" }).click();
  await expect(steps.getByRole("tab", { name: "Check" })).toHaveAttribute("aria-selected", "true");
  await steps.getByRole("tab", { name: "Check" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(steps.getByRole("tab", { name: "Fix" })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("link", { name: "This run's job page" })).toHaveAttribute("href", `/jobs/${run.id}`);
});

test("job page: a verified job says what passed, why and what next, above everything else", async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto("/jobs/job_demo_1");
  const plain = page.getByTestId("job-plain");
  await expect(plain).toContainText("Passed. The largest error is 0.31 mm; the limit is 0.50 mm.");
  await expect(plain).toContainText("nothing the AI claimed counts");
  await expect(plain.getByRole("link", { name: "Check the fit" })).toHaveAttribute("href", "/jobs/job_demo_1/fit");
  const top = await plain.boundingBox();
  const viewport = page.viewportSize()!;
  expect(top!.y).toBeLessThan(viewport.height);
  await expectAccessible(page);
  expect(realErrors(errors)).toEqual([]);
});

test("job page: best effort reads as not verified with the record's reason; a paused job asks for its answer", async ({ page }) => {
  await setup(page);
  await page.goto("/jobs/job_best");
  const plain = page.getByTestId("job-plain");
  await expect(plain).toContainText("Not verified. The closest model is 0.83 mm off; the limit is 0.50 mm.");
  await expect(plain).toContainText("the top outline is off by up to 0.83 mm");
  await expect(plain.getByRole("link", { name: "Start a new fix" })).toHaveAttribute("href", "/fix");
  await expect(plain).not.toContainText("Passed");
  await page.goto("/jobs/job_paused");
  await expect(page.getByTestId("job-plain")).toContainText("Paused: it needs one answer from you.");
  await expect(page.getByLabel("Answer in millimetres")).toBeVisible();
});

test("results: four plain answers from the report come first, and real parts say not measured", async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto("/results");
  const plain = page.getByTestId("results-plain");
  await expect(plain.getByRole("term")).toHaveText(["How close does it get?", "On photos of real objects?", "Does it turn bad input away?", "On real broken parts?"]);
  await expect(plain.getByRole("link", { name: "See the table" })).toHaveCount(4);
  await expect(plain).toContainText("Not measured yet.");
  await expect(plain.getByRole("link", { name: "the test evidence page" })).toHaveAttribute("href", "/proof#scale");
  await expectAccessible(page);
  expect(realErrors(errors)).toEqual([]);
});

test("glossary words explain themselves on hover, focus and tap, and Esc closes them", async ({ page }, info) => {
  await setup(page);
  await page.goto("/results");
  const word = page.getByTestId("results-plain").getByRole("button", { name: "IoU", exact: true });
  const tip = page.getByRole("tooltip");
  await word.scrollIntoViewIfNeeded();
  if (info.project.name.startsWith("mobile")) {
    await word.tap();
    await expect(tip).toContainText("How much the two outlines overlap");
    await word.tap();
    await expect(tip).toHaveCount(0);
  } else {
    await word.hover();
    await expect(tip).toContainText("How much the two outlines overlap");
    await page.mouse.move(0, 0);
    await expect(tip).toHaveCount(0);
  }
  await word.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(tip).toContainText("How much the two outlines overlap");
  await expect(word).toHaveAttribute("aria-describedby", /.+/);
  await page.keyboard.press("Escape");
  await expect(tip).toHaveCount(0);

  await page.goto("/jobs/job_demo_1");
  const verifier = page.getByTestId("job-plain").getByRole("button", { name: "verifier", exact: true });
  await verifier.scrollIntoViewIfNeeded();
  await verifier.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(tip).toContainText("only it can mark a part verified");
});
