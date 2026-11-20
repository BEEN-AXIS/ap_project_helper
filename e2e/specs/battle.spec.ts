// Two browser contexts (alice and bob) play a full ranked match through the UI.
// The FakeRunner reads "# VERDICT: ..." from the code, so every hit is deterministic.
import { expect, test, type Browser, type Page } from "@playwright/test";

declare global {
  interface Window {
    __algoarena?: { setCode(code: string): void; submitNow(): void };
    __vfx?: { events: { show: string; step: string }[] };
  }
}

async function signIn(browser: Browser, name: string, pass: string, errors: string[]): Promise<Page> {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`${name}: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/fonts\.googleapis|net::/.test(m.text())) errors.push(`${name} console: ${m.text()}`);
  });
  await page.goto("/login");
  await page.fill('input[name="username"]', name);
  await page.fill('input[name="password"]', pass);
  await page.click('button[type="submit"]');
  await page.waitForURL("**/lobby");
  return page;
}

async function openCard(page: Page, tier: number): Promise<void> {
  await page.locator(`[data-testid^="card-"][data-tier="${tier}"]`).first().click();
  await expect(page.getByTestId("workspace")).toBeVisible();
}

async function submit(page: Page, code: string): Promise<void> {
  await page.evaluate((c) => window.__algoarena!.setCode(c), code);
  await page.evaluate(() => window.__algoarena!.submitNow());
}

const hp = (page: Page, who: "me" | "opp") => page.getByTestId(`hp-text-${who}`);

test("ranked match: hit, backfire, block, KO and result on both screens", async ({ browser }) => {
  const errors: string[] = [];
  const a = await signIn(browser, "alice", "alice-pass", errors);
  const b = await signIn(browser, "bob", "bob-pass", errors);

  for (const p of [a, b]) {
    await p.getByTestId("mode-ranked").click();
    await p.getByTestId("start").click();
    await p.waitForURL("**/queue");
  }
  await a.getByTestId("accept").click();
  await b.getByTestId("accept").click();
  await a.waitForURL("**/battle/**");
  await b.waitForURL("**/battle/**");
  expect(a.url()).toBe(b.url());
  await expect(a.locator('[data-testid="battle"][data-status="live"]')).toBeVisible({ timeout: 20_000 });
  await expect(b.locator('[data-testid="battle"][data-status="live"]')).toBeVisible({ timeout: 20_000 });

  // Every card names its difficulty, which picks the weapon animation.
  for (const p of [a, b]) {
    const levels = await p.locator('[data-testid^="card-level-"]').allTextContents();
    expect(levels.sort()).toEqual(["EASY", "MEDIUM", "NORMAL", "TOUGH"]);
  }

  // 1. Alice runs the samples, then lands an on-level hit (8,000 at tier 2).
  await openCard(a, 2);
  await a.evaluate(() => window.__algoarena!.setCode("# VERDICT: AC\n# DELAY_MS: 40\nprint('fire')\n"));
  await a.getByTestId("run").click();
  await expect(a.getByTestId("run-row-0")).toBeVisible();
  await submit(a, "# VERDICT: AC\n# DELAY_MS: 40\nprint('fire')\n");
  await expect(hp(b, "me")).toHaveText("20,000 / 28,000");
  await expect(hp(a, "opp")).toHaveText("20,000 / 28,000");

  // 2. Bob raises a Block, then a wrong answer on his tier-3 card backfires (6,000 recoil).
  await b.getByTestId("block").click();
  await openCard(b, 3);
  await submit(b, "# VERDICT: WA 2\n# DELAY_MS: 30\nprint(0)\n");
  await expect(b.getByTestId("submit-verdict")).toContainText("WRONG ANSWER");
  await expect(hp(b, "me")).toHaveText("14,000 / 28,000");
  await expect(hp(a, "opp")).toHaveText("14,000 / 28,000");

  // 3. Alice's tier-4 hit is absorbed by the shield; the card is still spent.
  await a.keyboard.press("Escape");
  await a.waitForTimeout(3_200); // submit cooldown
  await openCard(a, 4);
  await submit(a, "# VERDICT: AC\n# DELAY_MS: 20\n");
  await a.waitForTimeout(1_500);
  await expect(hp(b, "me")).toHaveText("14,000 / 28,000");

  // 4. The re-dealt tier-4 card finishes him.
  await a.keyboard.press("Escape");
  await a.waitForTimeout(3_300);
  await openCard(a, 4);
  await submit(a, "# VERDICT: AC\n# DELAY_MS: 20\n");

  await a.waitForURL("**/result/**", { timeout: 20_000 });
  await b.waitForURL("**/result/**", { timeout: 20_000 });
  await expect(a.getByTestId("outcome")).toContainText("VICTORY");
  await expect(b.getByTestId("outcome")).toContainText("DEFEAT");
  await expect(a.getByTestId("rating-delta")).toContainText("+");
  await expect(b.getByTestId("rating-delta")).toContainText("-");

  const steps = await a.evaluate(() => (window.__vfx?.events ?? []).map((e) => `${e.show}:${e.step}`));
  for (const s of ["hit:impact", "backfire:explosion", "block:impact", "ko-hit:ko"]) expect(steps).toContain(s);
  expect(errors).toEqual([]);
});

test("the weapons locker equips a weapon and previews all four forms", async ({ browser }) => {
  const errors: string[] = [];
  const p = await signIn(browser, "bob", "bob-pass", errors);
  await p.goto("/locker");
  await p.getByTestId("tab-weapon").click();
  await p.getByTestId("skin-weapon.gun").click();
  for (let i = 0; i < 4; i++) {
    await p.getByTestId(`preview-level-${i}`).click();
    await p.waitForTimeout(400);
  }
  await p.getByTestId("equip").click();
  await expect(p.getByTestId("skin-weapon.gun").getByText("Equipped")).toBeVisible();
  expect(errors).toEqual([]);
});

test("double-clicking submit creates one submission", async ({ browser }) => {
  const errors: string[] = [];
  const a = await signIn(browser, "alice", "alice-pass", errors);
  await a.getByTestId("mode-bot").click();
  await a.getByTestId("start").click();
  await a.waitForURL("**/battle/**");
  await expect(a.locator('[data-testid="battle"][data-status="live"]')).toBeVisible({ timeout: 20_000 });
  await openCard(a, 1);
  await a.evaluate(() => window.__algoarena!.setCode("# VERDICT: AC\n# DELAY_MS: 300\n"));
  await a.evaluate(() => {
    window.__algoarena!.submitNow();
    window.__algoarena!.submitNow();
  });
  await expect(a.getByTestId("submit-verdict")).toBeVisible();
  await a.keyboard.press("Escape"); // back to the hand, where the battle log lives
  await expect(a.getByTestId("battle-log").getByText(/Submitting /)).toHaveCount(1);
  expect(errors).toEqual([]);
});
