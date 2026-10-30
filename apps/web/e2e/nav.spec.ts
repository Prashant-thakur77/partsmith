import { expect, test } from "@playwright/test";
import { setup } from "./helpers";

test("header: at most six items, the Fix a part button always in view, the rest in the footer", async ({ page }) => {
  await setup(page);
  await page.goto("/");
  const header = page.getByRole("banner");
  // the primary action is in the header itself on every screen size, not only in the menu
  await expect(header.getByRole("link", { name: "Fix a part" })).toBeVisible();
  await expect(header.getByRole("link", { name: /API online/ })).toHaveAttribute("title", /API online/);
  const wide = (page.viewportSize()?.width ?? 1440) >= 768;
  if (wide) {
    const main = page.getByRole("navigation", { name: "Main" });
    const labels = (await main.getByRole("link").allInnerTexts()).map((t) => t.replace(/\s*\d+(\s+waiting)?\s*$/, "").trim());
    expect(labels).toEqual(["Parts", "How it works", "Review", "For developers"]);
    expect(labels.length + 1).toBeLessThanOrEqual(6); // + the Fix a part button
    await expect(main.getByRole("link", { name: "For developers" })).toHaveAttribute("href", "/agents");
  } else {
    await page.getByRole("button", { name: "Open menu" }).click();
    const mobile = page.getByRole("navigation", { name: "Mobile" });
    await expect(mobile.getByRole("link", { name: "How it works" })).toBeVisible();
    await expect(mobile.getByRole("link", { name: "For developers" })).toBeVisible();
    await page.keyboard.press("Escape");
  }
  const footer = page.getByRole("contentinfo");
  for (const [label, href] of [
    ["Accuracy", "/results"],
    ["Which AI did what", "/models"],
    ["What it learned", "/lessons"],
    ["Judge path", "/judges"],
    ["Make a part family", "/factory"],
    ["Repair shops", "/shop"],
    ["All jobs", "/jobs"],
    ["Request a part", "/requests"],
    ["Try a sample", "/jobs/demo"],
  ] as const) {
    await expect(footer.getByRole("link", { name: label, exact: true })).toHaveAttribute("href", href);
  }
});

test("/how explains the five steps, links each to where it can be seen, and defines the words", async ({ page }, info) => {
  test.skip(!info.project.name.startsWith("desktop-light") && !info.project.name.startsWith("mobile-light"), "content check, light themes");
  await setup(page);
  await page.goto("/how");
  const steps = page.getByRole("region", { name: "The five steps" }).getByRole("listitem");
  await expect(steps).toHaveCount(5);
  await expect(page.getByRole("link", { name: "Watch a recorded run" })).toHaveAttribute("href", "/judges");
  await expect(page.getByRole("link", { name: "Which AI did what" }).first()).toHaveAttribute("href", "/models");
  await expect(page.getByRole("heading", { name: "The model proposes, code decides" })).toBeVisible();
  for (const term of ["Hausdorff (the gap)", "IoU", "Residual", "Verified", "Best effort", "Recorded run (replay)", "Mock", "Synthetic"]) {
    await expect(page.getByRole("term").filter({ hasText: term }).first()).toBeVisible();
  }
});
