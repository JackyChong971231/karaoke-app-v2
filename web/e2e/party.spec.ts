import { expect, probe, queueLibrary, test, waitForTv } from "./party";

test("filler plays on an empty queue", async ({ party }) => {
  const tv = await party.tv();
  const p = await waitForTv(tv, (x) => x.stage.kind === "playing" && x.audible > 0.5, "filler is audible");
  expect(p.playId).not.toBeNull();
  const phone = await party.phone("Alice");
  await expect(phone.getByTestId("now-playing")).toContainText("Sing-along filler");
  await phone.getByTestId("tab-queue").click();
  await expect(phone.getByTestId("queue-empty")).toBeVisible();
});

test("two phones queue and the fairness order shows", async ({ party }) => {
  const tv = await party.tv();
  await waitForTv(tv, (x) => x.stage.kind === "playing", "filler started");
  const alice = await party.phone("Alice");
  const bob = await party.phone("Bob");
  // Hold the filler so no queued song starts while we read the order.
  await alice.getByTestId("pause").click();
  await waitForTv(tv, (x) => x.paused, "filler paused");

  await queueLibrary(alice, "Morning Sun");
  await queueLibrary(alice, "河流");
  await queueLibrary(bob, "Night Drive");

  await bob.getByTestId("tab-queue").click();
  await expect(bob.getByTestId("queue-row-title")).toHaveText(["Morning Sun", "Night Drive", "河流"]);
  await expect(bob.getByTestId("queue-row-singer")).toHaveText([/Alice/, /Bob \(you\)/, /Alice/]);
  await expect(bob.getByTestId("tv-status")).toHaveText(/TV on/);
});

test("skip advances exactly one song with a double tap", async ({ party }) => {
  const tv = await party.tv();
  const filler = await waitForTv(tv, (x) => x.stage.kind === "playing", "filler started");
  const alice = await party.phone("Alice");
  const bob = await party.phone("Bob");
  await alice.getByTestId("pause").click();
  await queueLibrary(alice, "Morning Sun");
  await queueLibrary(alice, "河流");

  await alice.getByTestId("tab-now").click();
  await alice.getByTestId("skip").click();
  // The filler may itself be Morning Sun, so wait for the queued play (sung by Alice), not the title.
  await expect(alice.getByTestId("now-playing")).toContainText("Alice");
  await expect(alice.getByTestId("now-title")).toHaveText("Morning Sun");
  await bob.getByTestId("tab-now").click();
  await expect(bob.getByTestId("now-playing")).toContainText("Alice");
  const first = await waitForTv(
    tv,
    (x) => x.playId === (filler.playId ?? 0) + 1 && x.loadedSongId === "fklib000001" && x.stage.kind === "playing",
    "queued song 1 on TV",
  );

  await alice.getByTestId("skip").dblclick();
  await expect(bob.getByTestId("now-title")).toHaveText("河流");
  const second = await waitForTv(
    tv,
    (x) => x.loadedSongId === "fklib000002" && x.stage.kind === "playing",
    "queued song 2 on TV",
  );
  expect(second.playId).toBe((first.playId ?? 0) + 1);
  await alice.waitForTimeout(1500);
  expect((await probe(tv)).playId).toBe(second.playId);
  await expect(alice.getByTestId("now-title")).toHaveText("河流");
});

test("vocal slider and key change reach the TV", async ({ party }) => {
  const tv = await party.tv();
  await waitForTv(tv, (x) => x.stage.kind === "playing", "filler started");
  const phone = await party.phone("Alice");
  await phone.getByTestId("pause").click();
  await waitForTv(tv, (x) => x.paused, "paused");

  await phone.getByTestId("vocal-slider").fill("70");
  await expect(phone.getByTestId("vocal-value")).toHaveText(/70%/);
  await waitForTv(tv, (x) => Math.abs(x.vocalGain - 0.7) < 0.001, "vocal gain 0.7 on TV");

  await phone.getByTestId("key-up").click();
  await expect(phone.getByTestId("key-value")).toHaveText("+1");
  await phone.getByTestId("key-up").click();
  await expect(phone.getByTestId("key-value")).toHaveText("+2");
  await waitForTv(tv, (x) => x.semitones === 2, "key +2 on TV");
  await phone.getByTestId("key-down").click();
  await expect(phone.getByTestId("key-value")).toHaveText("+1");
  await waitForTv(tv, (x) => x.semitones === 1, "key +1 on TV");
});

test("lyrics probe shows the current line and the fill progressing", async ({ party }) => {
  const tv = await party.tv();
  const early = await waitForTv(
    tv,
    (x) => x.stage.kind === "playing" && x.audible > 1.2 && x.audible < 2.6,
    "inside line 0",
  );
  expect(early.slots[0]?.text).toBe("Sing along with the fake world");
  expect(early.slots[1]?.text).toBe("測試歌詞顯示");
  const sum = (f: number[] | undefined): number => (f ?? []).reduce((a, b) => a + b, 0);
  const later = await waitForTv(tv, (x) => x.audible > early.audible + 0.5 && x.audible < 3.3, "later in line 0");
  expect(sum(later.slots[0]?.fills)).toBeGreaterThan(sum(early.slots[0]?.fills));
  expect(sum(later.slots[1]?.fills)).toBe(0);

  const cjk = await waitForTv(tv, (x) => x.audible > 4.2 && x.audible < 5.5, "inside line 1");
  expect(cjk.slots[1]?.text).toBe("測試歌詞顯示");
  expect(sum(cjk.slots[1]?.fills)).toBeGreaterThan(0);
  // Line 0 finished, so its slot already shows line 2.
  expect(cjk.slots[0]?.text).toBe("Every word lights up in blue");
  expect(Math.abs(cjk.videoTime - cjk.display)).toBeLessThan(0.5);
});

test("TV reload resumes the same play at its position", async ({ party }) => {
  const tv = await party.tv();
  await waitForTv(tv, (x) => x.stage.kind === "playing" && x.audible > 2.5, "filler past 2.5 s");
  const phone = await party.phone("Alice");
  await phone.getByTestId("pause").click();
  const paused = await waitForTv(tv, (x) => x.paused, "paused");
  await tv.waitForTimeout(600);
  const before = await probe(tv);

  await tv.reload();
  const after = await waitForTv(tv, (x) => x.stage.kind === "playing", "playing again after reload");
  expect(after.playId).toBe(paused.playId);
  expect(after.paused).toBe(true);
  expect(Math.abs(after.audible - before.audible)).toBeLessThan(0.5);

  await phone.getByTestId("pause").click();
  const resumed = await waitForTv(tv, (x) => !x.paused && x.audible > before.audible + 0.3, "resumed forward");
  expect(resumed.playId).toBe(paused.playId);
});

test("the vocal switch turns the vocal off and back to its level", async ({ party }) => {
  const tv = await party.tv();
  await waitForTv(tv, (x) => x.stage.kind === "playing", "filler started");
  const phone = await party.phone("Alice");
  await phone.getByTestId("vocal-slider").fill("40");
  await waitForTv(tv, (x) => Math.abs(x.vocalGain - 0.4) < 0.001, "vocal gain 0.4 on TV");

  await phone.getByTestId("vocal-toggle").click();
  await expect(phone.getByTestId("vocal-toggle")).toHaveAttribute("aria-checked", "false");
  await waitForTv(tv, (x) => x.vocalGain === 0, "vocal off on TV");
  await expect(tv.getByTestId("tv-vocal")).toHaveText(/Vocal\s*Off/);
  await phone.getByTestId("vocal-toggle").click();
  await expect(phone.getByTestId("vocal-value")).toHaveText(/40%/);
  await waitForTv(tv, (x) => Math.abs(x.vocalGain - 0.4) < 0.001, "vocal back to 0.4 on TV");
  await expect(tv.getByTestId("tv-vocal")).toHaveText(/Vocal\s*40%/);

  await expect(tv.getByTestId("tv-key")).toHaveText(/Key\s*Original/);
  await phone.getByTestId("key-down").click();
  await expect(tv.getByTestId("tv-key")).toHaveText(/Key\s*-1/);
});

test("the control page shows every screen at once and drives the TV with the mouse", async ({ party }) => {
  const tv = await party.tv();
  await waitForTv(tv, (x) => x.stage.kind === "playing", "filler started");
  const control = await party.control("Host");
  await expect(control.getByTestId("now-playing")).toBeVisible();
  await expect(control.getByTestId("search-input")).toBeVisible();
  await expect(control.getByTestId("tab-now")).toHaveCount(0);

  await control.getByTestId("pause").click();
  await waitForTv(tv, (x) => x.paused, "paused from the control page");
  await queueLibrary(control, "Morning Sun");
  await expect(control.getByTestId("queue-row-title")).toHaveText(["Morning Sun"]);
});

test("the TV shows a full-screen button when the mouse moves", async ({ party }) => {
  // A kiosk window that fills the screen shows no button, so this is an ordinary window.
  const tv = await party.tv({ width: 1280, height: 720 });
  const button = tv.getByTestId("tv-fullscreen");
  await expect(button).not.toHaveClass(/is-active/);
  await tv.mouse.move(200, 200);
  await tv.mouse.move(220, 210);
  await expect(button).toHaveClass(/is-active/);
  await expect(button).toHaveAttribute("aria-label", "Full screen");
});
