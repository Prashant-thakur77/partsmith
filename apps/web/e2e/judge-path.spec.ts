import { expect, test } from "@playwright/test";
import { expectAccessible, realErrors, setup } from "./helpers";

const lightDesktop = (name: string) => name.startsWith("desktop-light");

test("the film stays off YouTube until someone presses play", async ({ page }, info) => {
  test.skip(!lightDesktop(info.project.name), "behaviour check");
  const requests: string[] = [];
  page.on("request", (r) => requests.push(r.url()));
  await setup(page);
  await page.route(/youtube/, (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<html></html>" }));
  await page.goto("/#film");
  const play = page.getByRole("button", { name: /Play the PartSmith demo film/ });
  await expect(play).toBeVisible();
  await page.waitForTimeout(600);
  expect(requests.filter((u) => /youtube/.test(u))).toEqual([]);
  await play.click();
  const frame = page.locator('iframe[title="PartSmith demo film"]');
  await expect(frame).toHaveAttribute("src", /^https:\/\/www\.youtube-nocookie\.com\/embed\//);
  await expect(page.getByRole("link", { name: "Open on YouTube" })).toHaveAttribute("href", /youtu\.be/);
});

test("the hero knob moves between real baked meshes and the size follows", async ({ page }, info) => {
  test.skip(!lightDesktop(info.project.name), "behaviour check");
  const { errors } = await setup(page);
  const meshes: string[] = [];
  page.on("response", (r) => {
    if (r.url().endsWith(".bin")) meshes.push(`${r.status()} ${new URL(r.url()).pathname}`);
  });
  await page.goto("/");
  const knob = page.getByRole("slider", { name: "Overall length including tongues" });
  await expect(knob).toBeVisible();
  const hero = page.locator("#try");
  await expect(hero.getByText(/45\.30 × 30\.01 × 5\.00 mm/)).toBeVisible();
  await expect(hero.getByText("recorded run · rendered sample")).toBeVisible();
  await expect(hero.getByText(/Real CadQuery output/)).toBeVisible();
  await knob.focus();
  await page.keyboard.press("ArrowRight");
  await expect(hero.getByText(/50\.30 × 30\.01 × 5\.00 mm/)).toBeVisible();
  await expect.poll(() => meshes.some((m) => m === "200 /deck/models/battery-cover-45mm__length_50.3.bin")).toBeTruthy();
  await expect(page.getByRole("img", { name: /length including tongues 50\.30 mm/ })).toBeVisible();
  expect(realErrors(errors)).toEqual([]);
});

test("the page offers one way through, and the deck and code are one click away", async ({ page }, info) => {
  test.skip(!lightDesktop(info.project.name) && !info.project.name.startsWith("mobile-light"), "content check");
  await setup(page);
  await page.goto("/");
  const path = page.getByRole("navigation", { name: "A way through this page" });
  await expect(path.getByRole("link")).toHaveCount(4);
  await expect(path.getByRole("link", { name: /Watch/ })).toHaveAttribute("href", "#film");
  await expect(path.getByRole("link", { name: /Try the knob/ })).toHaveAttribute("href", "#try");
  await expect(path.getByRole("link", { name: /See the proof/ })).toHaveAttribute("href", "#proof");
  await expect(path.getByRole("link", { name: /Open the code/ })).toHaveAttribute("href", /github\.com/);
  const footer = page.getByRole("contentinfo");
  await expect(footer.getByRole("link", { name: "Interactive deck" })).toHaveAttribute("href", "/deck/index.html");
  await expect(footer.getByRole("link", { name: "Source code" })).toHaveAttribute("href", /github\.com/);
});

test("the judge page opens with the film, the deck and the code", async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto("/judges");
  await expect(page.getByRole("button", { name: /Play the PartSmith demo film/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "Interactive deck" }).first()).toHaveAttribute("href", "/deck/index.html");
  await expect(page.getByRole("link", { name: /Source code/ }).first()).toHaveAttribute("href", /github\.com/);
  await page.waitForLoadState("networkidle");
  const vw = page.viewportSize()!.width;
  expect(await page.evaluate((w) => document.documentElement.scrollWidth - w, vw)).toBeLessThanOrEqual(0);
  await expectAccessible(page);
  expect(realErrors(errors)).toEqual([]);
});
