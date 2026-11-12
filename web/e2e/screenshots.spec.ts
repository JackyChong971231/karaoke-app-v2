import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { expect, queueLibrary, test, waitForTv } from "./party";

const dir = resolve(import.meta.dirname, "screenshots");
const shot = (page: Page, name: string): Promise<Buffer> => page.screenshot({ path: resolve(dir, `${name}.png`) });

test("screenshots of the TV and phone pages", async ({ party, browser }) => {
  const tv = await party.tv();
  await waitForTv(tv, (x) => x.stage.kind === "playing", "filler started");

  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await page.goto(`${party.url}/`);
  await shot(page, "phone-name-gate");
  await page.close();

  const alice = await party.phone("Alice");
  const bob = await party.phone("Bob");
  await alice.getByTestId("pause").click();
  await waitForTv(tv, (x) => x.paused, "paused");
  await queueLibrary(alice, "Morning Sun");
  await queueLibrary(bob, "Night Drive");
  await queueLibrary(alice, "河流");

  await bob.getByTestId("tab-search").click();
  await bob.getByTestId("search-input").fill("fake");
  await expect(bob.getByTestId("online-result").first()).toBeVisible();
  await shot(bob, "phone-search");
  await bob.getByTestId("online-result").first().getByTestId("queue-online").click();
  await expect(bob.getByTestId("toast").filter({ hasText: "Queued" }).last()).toBeVisible();

  await bob.getByTestId("search-input").fill("no video");
  await bob.getByTestId("online-result").filter({ hasText: "No Video" }).first().getByTestId("queue-online").click();
  await expect(bob.getByTestId("video-candidate").first()).toBeVisible();
  await bob.waitForTimeout(400);
  await shot(bob, "phone-video-picker");
  await bob.getByTestId("video-candidate").first().click();
  await expect(bob.getByTestId("toast").filter({ hasText: "No Video" })).toBeVisible();

  await alice.getByTestId("tab-queue").click();
  await expect(alice.getByTestId("queue-row")).toHaveCount(5);
  await shot(alice, "phone-queue");
  await alice.getByTestId("queue-row-open").nth(1).click();
  await expect(alice.getByTestId("entry-play-next")).toBeVisible();
  await alice.waitForTimeout(400);
  await shot(alice, "phone-entry-menu");
  await alice.getByTestId("entry-play-next").click();
  await expect(alice.getByTestId("queue-row-title").first()).toHaveText("Night Drive");

  await alice.getByTestId("tab-now").click();
  await alice.getByTestId("vocal-slider").fill("35");
  await alice.getByTestId("key-up").click();
  await expect(alice.getByTestId("key-value")).toHaveText("+1");
  await alice.getByTestId("pause").click();
  await waitForTv(tv, (x) => !x.paused && x.audible > 1.5 && x.audible < 3.2, "lyrics on screen");
  await shot(tv, "tv-playing-1920");
  await shot(alice, "phone-now-playing");
  await alice.getByTestId("open-settings").click();
  await alice.waitForTimeout(400);
  await shot(alice, "phone-settings");

  await tv.setViewportSize({ width: 390, height: 844 });
  await tv.waitForTimeout(300);
  await shot(tv, "tv-at-phone-width-390");
  await bob.setViewportSize({ width: 1920, height: 1080 });
  await bob.getByTestId("tab-now").click();
  await bob.waitForTimeout(300);
  await shot(bob, "phone-at-tv-width-1920");
});
