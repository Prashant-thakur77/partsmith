import { expect, test } from "@playwright/test";
import { expectAccessible, realErrors, setup, shot } from "./helpers";

/** Desktop loads the 3D view on its own; phones show the poster and load 3D on tap. */
async function show3d(p: import("@playwright/test").Page) {
  if ((p.viewportSize()?.width ?? 1440) < 768) await p.getByRole("button", { name: "View in 3D" }).first().click();
  await expect(p.locator("canvas").first()).toBeVisible();
}

type PageCase = { name: string; path: string; ready: (p: import("@playwright/test").Page) => Promise<void>; full?: boolean; opts?: Parameters<typeof setup>[1] };

const PAGES: PageCase[] = [
  { name: "home", path: "/", ready: async (p) => { await expect(p.getByRole("heading", { level: 1 })).toBeVisible(); await expect(p.getByText("verified parts").first()).toBeVisible(); await show3d(p); } },
  { name: "fix", path: "/fix", ready: async (p) => { await expect(p.getByRole("heading", { name: "From photo to verified part" })).toBeVisible(); } },
  { name: "calibrate", path: "/calibrate", ready: async (p) => { await expect(p.getByRole("slider", { name: "Card width on screen" })).toBeVisible(); } },
  { name: "mat", path: "/mat", full: false, ready: async (p) => { await expect(p.getByRole("img", { name: /1:1 scale/ })).toBeVisible(); } },
  { name: "jobs", path: "/jobs", ready: async (p) => { await expect(p.getByText("L-bracket", { exact: true }).first()).toBeVisible(); } },
  { name: "jobs-demo", path: "/jobs/demo", ready: async (p) => { await expect(p.getByRole("button", { name: "Run this sample" })).toBeVisible(); } },
  { name: "workspace", path: "/jobs/job_demo_1", ready: async (p) => { await expect(p.getByRole("status", { name: /Verified/ })).toBeVisible(); await show3d(p); } },
  { name: "workspace-paused", path: "/jobs/job_paused", ready: async (p) => { await expect(p.getByText("How deep is the D-shaft hole?")).toBeVisible(); } },
  { name: "fit", path: "/jobs/job_demo_1/fit", full: false, ready: async (p) => { await expect(p.getByText("Lay the part exactly on the pink outline")).toBeVisible(); } },
  { name: "parts", path: "/parts", ready: async (p) => { await expect(p.getByRole("link", { name: /L-bracket/ }).first()).toBeVisible(); } },
  { name: "part", path: "/parts/l-bracket", ready: async (p) => { await expect(p.getByRole("heading", { name: "L-bracket", level: 1 })).toBeVisible(); await show3d(p); } },
  { name: "steer", path: "/steer?id=steer_1", ready: async (p) => { await expect(p.getByRole("listbox", { name: /Approval queue/ })).toBeVisible(); } },
  { name: "bench", path: "/bench", ready: async (p) => { await expect(p.getByText("N = 40")).toBeVisible(); } },
  { name: "status", path: "/status", ready: async (p) => { await expect(p.getByText("Providers by stage")).toBeVisible(); } },
  { name: "agents", path: "/agents", ready: async (p) => { await expect(p.getByRole("heading", { name: "Connect over MCP" })).toBeVisible(); } },
  { name: "judges", path: "/judges", ready: async (p) => { await expect(p.getByRole("button", { name: "Play" })).toBeVisible(); } },
  { name: "not-found", path: "/definitely-not-here", ready: async (p) => { await expect(p.getByRole("heading", { name: /doesn.t exist/ })).toBeVisible(); } },
  { name: "home-offline", path: "/", opts: { offline: true }, ready: async (p) => { await expect(p.getByText("The PartSmith API is offline").first()).toBeVisible(); } },
  { name: "parts-empty", path: "/parts?q=zzz", opts: { emptyRegistry: true }, ready: async (p) => { await expect(p.getByRole("button", { name: "Request this part" })).toBeVisible(); } },
  { name: "bench-pending", path: "/bench", opts: { noBench: true }, ready: async (p) => { await expect(p.getByText("No bench report has been generated yet")).toBeVisible(); } },
];

for (const c of PAGES) {
  test(`${c.name} renders, is accessible and has no console errors`, async ({ page }, info) => {
    const { errors } = await setup(page, c.opts);
    const res = await page.goto(c.path);
    expect(res?.status(), "HTTP status").toBeLessThan(c.name === "not-found" ? 500 : 400);
    await c.ready(page);
    await page.waitForLoadState("networkidle");
    // Compare with the configured viewport: on mobile emulation a too-wide element silently widens innerWidth.
    const vw = page.viewportSize()!.width;
    const overflow = await page.evaluate((w) => document.documentElement.scrollWidth - w, vw);
    expect(overflow, "no horizontal page scroll").toBeLessThanOrEqual(0);
    await shot(page, info, c.name, c.full !== false);
    await expectAccessible(page);
    const errs = realErrors(errors).filter((e) => !(c.opts?.offline && /502|Failed to load resource/.test(e)) && !(c.name === "not-found" && /404/.test(e)) );
    expect(errs, errs.join("\n")).toEqual([]);
  });
}

test("llms.txt and prompt.txt are served as text", async ({ request }) => {
  const llms = await request.get("/llms.txt");
  expect(llms.ok()).toBeTruthy();
  expect(llms.headers()["content-type"]).toContain("text/plain");
  expect(await llms.text()).toContain("## MCP tools");
  const prompt = await request.get("/prompt.txt");
  expect(await prompt.text()).toContain("Never rescale a part");
});
