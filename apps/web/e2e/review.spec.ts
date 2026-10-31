import { expect, test, type Page, type Request } from "@playwright/test";
import { asAdmin, expectAccessible, realErrors, setup, shot } from "./helpers";

const functional = (name: string) => name === "desktop-light";

/** Bodies of POST /review/<job> decisions (not the rules draft). */
function decisions(page: Page): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  page.on("request", (r: Request) => {
    if (r.method() === "POST" && /\/api\/v1\/review\/[^/]+$/.test(new URL(r.url()).pathname)) out.push(JSON.parse(r.postData() ?? "{}"));
  });
  return out;
}

/** The photo's box once the image has loaded and the layout has settled (two equal readings in a row). */
async function photoBox(page: Page) {
  const img = page.getByRole("img", { name: /Rectified top photo/ });
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
  await img.evaluate((el) => el.scrollIntoView({ block: "center" })); // clear of the decision bar pinned to the bottom
  let last = "";
  await expect
    .poll(async () => {
      const box = await img.boundingBox();
      const now = box && box.height > 40 ? JSON.stringify(box) : "";
      const stable = now !== "" && now === last;
      last = now;
      return stable;
    })
    .toBe(true);
  return (await img.boundingBox())!;
}

test("review page renders, is accessible, has no page scroll sideways and no console errors", async ({ page }, info) => {
  await asAdmin(page);
  const { errors } = await setup(page);
  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Review finished parts", level: 1 })).toBeVisible();
  await expect(page.getByRole("listbox", { name: /Review queue/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cupboard latch · review round 2" })).toBeVisible();
  await photoBox(page);
  await page.waitForLoadState("networkidle");
  const vw = page.viewportSize()!.width;
  expect(await page.evaluate((w) => document.documentElement.scrollWidth - w, vw), "no horizontal page scroll").toBeLessThanOrEqual(0);
  await shot(page, info, "review");
  await expectAccessible(page);
  expect(realErrors(errors)).toEqual([]);
});

test.describe("functional", () => {
  test.beforeEach(({}, info) => {
    test.skip(!functional(info.project.name), "functional flows run once");
  });

  test("queue items show round, the code's verdict, judge mode and cost; the stats strip and nav count come from the API", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    await page.goto("/review");
    const queue = page.getByRole("listbox", { name: /Review queue/ });
    const first = queue.getByRole("option").first();
    await expect(first).toContainText("Cupboard latch · review round 2");
    await expect(first).toContainText("round 2");
    await expect(first).toContainText("best effort · 0.62 mm");
    await expect(first).toContainText("judge mock");
    await expect(first).toContainText("$0.012");
    await expect(queue.getByRole("option").nth(2)).toContainText("replay");
    await expect(page.getByRole("note", { name: "Judge and reviewer agreement" })).toContainText("Judge agreed with the reviewer in 3/4 reviews (κ 0.50)");
    await expect(page.getByRole("note", { name: "Judge and reviewer agreement" })).toContainText("1 reviewer");
    await expect(page.getByRole("note", { name: "Judge and reviewer agreement" })).toContainText("1 test review not counted");
    await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /Review/ })).toContainText("2");
    const card = page.getByRole("region", { name: "Judge scorecard" });
    await expect(card).toContainText("Advice from the judge. Pass/fail comes from the measurements.");
    await expect(card).toContainText("judge: mock (rule-based)");
    await expect(card).toContainText("Fit for use");
    await expect(card.getByRole("img", { name: "4 out of 5" })).toBeVisible();
    // the earlier round's pin is drawn grey with the server's before → after numbers
    await expect(page.getByRole("region", { name: "Round history" })).toContainText("0.84 → 0.21 mm");
  });

  test("improve: two pins with notes, then I sends both pins and the note", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    const posts = decisions(page);
    await page.goto("/review");
    const b = await photoBox(page);
    await page.mouse.click(b.x + b.width * 0.25, b.y + b.height * 0.5);
    await expect(page.getByRole("button", { name: /^Pin 1/ })).toBeVisible();
    await page.getByLabel("Note for pin 1").fill("this corner was square");
    const b2 = await photoBox(page); // measured again: the note list may have moved the page
    await page.mouse.click(b2.x + b2.width * 0.75, b2.y + b2.height * 0.2);
    await page.getByLabel("Note for pin 2").fill("hole is for an M3 screw");
    await page.getByLabel("Note for the builder").fill("keep the clip face flat");
    await page.getByRole("heading", { level: 1 }).click();
    await page.keyboard.press("i");
    await expect.poll(() => posts.length).toBe(1);
    const body = posts[0] as { action: string; pins: { u: number; v: number; note: string }[]; note: string };
    expect(body.action).toBe("improve");
    expect(body.pins).toHaveLength(2);
    expect(body.pins[0]!.note).toBe("this corner was square");
    expect(body.pins[0]!.u).toBeCloseTo(0.25, 1);
    expect(body.pins[0]!.v).toBeCloseTo(0.5, 1);
    expect(body.pins[1]!.u).toBeCloseTo(0.75, 1);
    expect(body.note).toBe("keep the clip face flat");
    await expect(page.getByRole("note").filter({ hasText: "The next round is running" })).toContainText("job_rev_3");
  });

  test("a pin can be removed, and keys typed into a note do nothing", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    const posts = decisions(page);
    await page.goto("/review");
    const b = await photoBox(page);
    await page.mouse.click(b.x + b.width * 0.5, b.y + b.height * 0.5);
    await expect(page.getByRole("button", { name: /^Pin 1/ })).toBeVisible();
    await page.getByLabel("Note for pin 1").fill("air");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.getByRole("button", { name: "Remove pin 1" }).click();
    await expect(page.getByRole("button", { name: /^Pin 1/ })).toHaveCount(0);
    await page.getByRole("heading", { level: 1 }).click();
    await page.keyboard.press("i");
    await expect(page.getByRole("alert").filter({ hasText: "Add a pin on the photo, a note or a screenshot first." })).toBeVisible();
    expect(posts).toHaveLength(0);
  });

  test("accept: A opens the drafted rules; an unticked rule goes out with keep false", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    const posts = decisions(page);
    await page.goto("/review");
    await photoBox(page);
    await page.keyboard.press("a");
    const dialog = page.getByRole("dialog", { name: "Accept this part" });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("It stays best effort");
    await expect(dialog.getByRole("textbox", { name: "Rule 1" })).toHaveValue(/keep a broken corner square/);
    await dialog.getByLabel("Keep rule 2").uncheck();
    await dialog.getByRole("textbox", { name: "Rule 1" }).fill("latch: broken corners are square");
    await expect(dialog.getByRole("switch", { name: "Publish to the registry" })).toBeVisible();
    await dialog.getByRole("button", { name: "Accept" }).click();
    await expect.poll(() => posts.length).toBe(1);
    const body = posts[0] as { action: string; rules: { text: string; keep: boolean; source_pin: number | null }[]; publish: boolean };
    expect(body.action).toBe("accept");
    expect(body.publish).toBe(false);
    expect(body.rules).toEqual([
      { text: "latch: broken corners are square", keep: true, source_pin: 1 },
      { text: "latch: the clip face is the flat one", keep: false, source_pin: null },
    ]);
    await expect(dialog).toHaveCount(0);
  });

  test("reject: R opens a reason box; Reject stays disabled until there is a reason; Esc closes", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    const posts = decisions(page);
    await page.goto("/review");
    await photoBox(page);
    await page.keyboard.press("r");
    const dialog = page.getByRole("dialog", { name: "Reject this part" });
    await expect(dialog.getByRole("button", { name: "Reject" })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await page.keyboard.press("r");
    await dialog.getByLabel("Reason").fill("wrong part");
    await dialog.getByRole("button", { name: "Reject" }).click();
    await expect.poll(() => posts.length).toBe(1);
    expect(posts[0]).toMatchObject({ action: "reject", reason: "wrong part", pins: [] });
  });

  test("j/k move through the queue and the URL follows; a replay hides the publish toggle", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    await page.goto("/review");
    await photoBox(page);
    await page.keyboard.press("j");
    await expect(page).toHaveURL(/\?job=job_demo_1$/);
    await expect(page.getByRole("heading", { name: "L-bracket (synthetic sample)", level: 2 })).toBeVisible();
    await page.keyboard.press("k");
    await expect(page).toHaveURL(/\?job=job_rev_2$/);
    await page.goto("/review?job=job_replay_1");
    // a test review is labelled as one, never as a person's
    await expect(page.getByRole("note").filter({ hasText: "Accepted in a test review (not a person)" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Round history" })).toContainText("test review, not a person");
    await expect(page.getByRole("button", { name: "Accept" })).toHaveCount(0);
  });

  test("without an admin token the queue is read-only", async ({ page }) => {
    await setup(page);
    await page.goto("/review");
    await expect(page.getByLabel("Admin token")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Cupboard latch · review round 2" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Improve" })).toHaveCount(0);
    await expect(page.getByRole("group", { name: /click to add a pin/ })).toHaveCount(0);
  });

  test("an API without the review routes says so instead of showing anything", async ({ page }) => {
    await setup(page);
    await page.route("**/api/v1/openapi.json", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ openapi: "3.1.0", paths: {} }) }));
    await page.goto("/review");
    await expect(page.getByText("Review is not available on this server yet")).toBeVisible();
  });

  test("the photo and the 3D model sit side by side, with the files and the measurement check", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    await page.goto("/review?job=job_demo_1");
    await expect(page.getByRole("region", { name: "Should look like" }).getByRole("img", { name: /Rectified top photo/ })).toBeVisible();
    await expect(page.getByRole("region", { name: "Agent made" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Export" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Measurements" })).toContainText("code decides");
    await page.getByText("More views: slide between photo and model").click();
    await expect(page.getByRole("region", { name: "Your decision" })).toBeVisible();
  });

  test("a part that does not pass yet: the gap is circled and Improve leads", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    await page.goto("/review?job=job_rev_2");
    await expect(page.getByRole("region", { name: "Should look like" })).toContainText("biggest gap 0.62 mm");
    const bar = page.getByRole("region", { name: "Your decision" });
    await expect(bar.getByRole("button", { name: /Accept anyway/ })).toBeVisible();
    await page.goto("/review?job=job_demo_1"); // verified: a plain Accept
    await expect(page.getByRole("region", { name: "Your decision" }).getByRole("button", { name: /^Accept A$/ })).toBeVisible();
  });

  test("a pasted screenshot is uploaded and sent with Improve", async ({ page }) => {
    await asAdmin(page);
    await setup(page);
    const posts = decisions(page);
    await page.goto("/review?job=job_demo_1");
    const note = page.getByLabel("Note for the builder");
    await note.click();
    // a clipboard paste carrying a PNG, as the browser hands over a screenshot
    await note.evaluate(async (el) => {
      const c = document.createElement("canvas");
      c.width = c.height = 240;
      const blob = await new Promise<Blob>((ok) => c.toBlob((b) => ok(b!), "image/png"));
      const dt = new DataTransfer();
      dt.items.add(new File([blob], "screenshot.png", { type: "image/png" }));
      el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
    });
    await expect(page.getByRole("img", { name: "Attached picture 1" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Remove attached picture 1" })).toBeVisible();
    await page.getByRole("heading", { level: 1 }).click();
    await page.keyboard.press("i");
    await expect.poll(() => posts.length).toBe(1);
    const body = posts[0] as { action: string; attachments: string[]; pins: unknown[] };
    expect(body.action).toBe("improve");
    expect(body.pins).toHaveLength(0);
    expect(body.attachments).toEqual(["att_1.png"]);
  });

  test("job page shows the scorecard and a review badge that links to the review", async ({ page }) => {
    await setup(page);
    await page.goto("/jobs/job_demo_1");
    await expect(page.getByRole("region", { name: "Judge scorecard" })).toContainText("Pass/fail comes from the measurements.");
    const badge = page.getByRole("link", { name: /review: waiting · round 1/ });
    await expect(badge).toHaveAttribute("href", "/review?job=job_demo_1");
  });

  test("lessons show each rule's track record", async ({ page }) => {
    await setup(page);
    await page.goto("/lessons");
    await expect(page.getByText("Used in 3 jobs · later reviews: 2 accepted, 1 sent back, 0 rejected")).toBeVisible();
  });
});

test.describe("feedback log", () => {
  test.beforeEach(({}, info) => {
    test.skip(!functional(info.project.name), "functional flows run once");
  });

  test("each piece of feedback shows what, why and what the next round measured", async ({ page }) => {
    await setup(page);
    await page.goto("/review");
    await page.getByRole("link", { name: "Feedback log" }).click();
    await expect(page).toHaveURL(/\/review\/log$/);
    // one block per part (root job), newest activity first; each block lists its rounds in order
    const list = page.getByRole("list", { name: "Feedback by part, newest first" });
    const blocks = list.locator(":scope > li");
    await expect(blocks).toHaveCount(2);
    const first = blocks.first();
    await expect(first.getByRole("heading", { name: "Cupboard latch" })).toBeVisible();
    await expect(first).toContainText("“this corner was square”");
    await expect(first).toContainText("“the latch has to sit flush against the door frame”");
    await expect(first.getByRole("group", { name: /Gap before and after each round/ })).toContainText("0.84 mm");
    await expect(first.getByRole("group", { name: /Gap before and after each round/ })).toContainText("0.21 mm");
    await expect(first).toContainText("fixed");
    // the label carries the ledger's reason for it
    await expect(first.getByTestId("outcome-why")).toHaveText("· the gap is now within the 0.50 mm limit");
    await expect(first).toContainText("Given to 2 later jobs · their reviews: 1 accepted, 1 sent back, 0 rejected");
    await expect(first.getByRole("img", { name: "Close-up of pin 1 on the photo" })).toBeVisible();
    const second = blocks.nth(1);
    // a mixed log keeps the per-row label; reasons are never invented
    await expect(second).toContainText("test review, not a person");
    // no reason was given, and the block header does not lead with that
    await expect(second).not.toContainText("with a reason");
    await expect(second).not.toContainText("no reason given");
    await expect(page.getByRole("note").filter({ hasText: "Every entry below is a test review" })).toHaveCount(0);
    await expect(page.getByText("2 pieces of feedback · 1 fixed · 1 rejected")).toBeVisible();
    await page.getByLabel("Result").selectOption("rejected");
    await expect(page).toHaveURL(/outcome=rejected/);
    await expect(blocks).toHaveCount(1);
    // only test reviews left: one banner instead of a badge on every row
    await expect(page.getByRole("note").filter({ hasText: "Every entry below is a test review, not a person." })).toBeVisible();
    await expect(blocks.first()).not.toContainText("test review, not a person");
  });
});
