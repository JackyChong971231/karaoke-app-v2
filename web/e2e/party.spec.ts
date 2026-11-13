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

test("a second browser with a new name on the same phone is still one singer", async ({ party }) => {
  const tv = await party.tv();
  await waitForTv(tv, (x) => x.stage.kind === "playing", "filler started");
  const hog = await party.phone("Hog", "phone-h");
  const ben = await party.phone("Ben");
  const disguise = await party.phone("New Guy", "phone-h");
  await hog.getByTestId("pause").click();
  await waitForTv(tv, (x) => x.paused, "filler paused");

  await queueLibrary(hog, "Morning Sun");
  await queueLibrary(disguise, "河流");
  await queueLibrary(ben, "Night Drive");

  await disguise.getByTestId("tab-queue").click();
  await expect(disguise.getByTestId("queue-row-title")).toHaveText(["Morning Sun", "Night Drive", "河流"]);
  await expect(disguise.getByTestId("queue-row-singer")).toHaveText([/Hog \(you\)/, /^\s*Ben$/, /New Guy \(you\)/]);
});

test("a singer chooses the video: official first, or another one", async ({ party }) => {
  const tv = await party.tv();
  await waitForTv(tv, (x) => x.stage.kind === "playing", "filler started");
  const phone = await party.phone("Alice");
  await phone.getByTestId("pause").click();
  await phone.getByTestId("tab-search").click();

  await phone.getByTestId("search-input").fill("Fake Song One");
  await phone.getByTestId("online-result").filter({ hasText: "Fake Song One" }).getByTestId("queue-online").click();
  const videos = phone.getByTestId("video-candidate");
  await expect(videos).toHaveCount(3);
  await expect(videos.first()).toContainText("Official MV");
  await expect(videos.first()).toContainText("Official Music Video");
  await videos.filter({ hasText: "lyric video" }).click();
  await expect(phone.getByTestId("toast").filter({ hasText: "Queued “Fake Song One”" })).toBeVisible();

  // A library song can be sung with another video too; its own video is not offered again.
  await phone.getByTestId("search-input").fill("Morning Sun");
  await phone.getByTestId("library-result").filter({ hasText: "Morning Sun" }).getByTestId("library-other-videos").click();
  await expect(videos).toHaveCount(1);
  await expect(videos.first()).toContainText("live at the library");
  await videos.first().click();
  await expect(phone.getByTestId("toast").filter({ hasText: "Queued “Morning Sun”" })).toBeVisible();

  const state = (await (await fetch(`${party.url}/test/state`)).json()) as {
    party: { queue: { song: { id: string } }[] };
  };
  expect(state.party.queue.map((e) => e.song.id)).toEqual(["fkugc000012", "fkugc000101"]);
});

test("favourites: heart songs, queue from the list, and get them back on an empty browser", async ({ party }) => {
  const tv = await party.tv();
  await waitForTv(tv, (x) => x.stage.kind === "playing", "filler started");
  const alice = await party.phone("Alice");
  await alice.getByTestId("pause").click();
  await alice.getByTestId("tab-search").click();
  await expect(alice.getByTestId("favourites-empty")).toBeVisible();

  await alice.getByTestId("search-input").fill("Fake Song One");
  await alice.getByTestId("online-result").filter({ hasText: "Fake Song One" }).getByTestId("fav-heart").click();
  await expect(alice.getByTestId("toast").filter({ hasText: "Added “Fake Song One” to favourites" })).toBeVisible();
  await expect(alice.getByTestId("online-result").filter({ hasText: "Fake Song One" }).getByTestId("fav-heart"))
    .toHaveAttribute("aria-pressed", "true");
  await alice.getByTestId("search-input").fill("Morning Sun");
  await alice.getByTestId("library-result").filter({ hasText: "Morning Sun" }).getByTestId("fav-heart").click();
  await expect(alice.getByTestId("toast").filter({ hasText: "Added “Morning Sun” to favourites" })).toBeVisible();

  await alice.getByTestId("search-input").fill("");
  const rows = alice.getByTestId("favourite-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("Morning Sun");
  await rows.filter({ hasText: "Fake Song One" }).getByTestId("queue-favourite").click();
  await expect(alice.getByTestId("toast").filter({ hasText: "Queued “Fake Song One”" })).toBeVisible();
  await alice.getByTestId("tab-queue").click();
  await expect(alice.getByTestId("queue-row-title")).toHaveText(["Fake Song One"]);

  // The laptop's address changed, so Alice's browser starts empty. The app offers her list back.
  const again = await party.emptyPhone("Alice");
  await expect(again.getByTestId("restore-offer")).toContainText("Welcome back, Alice");
  await expect(again.getByTestId("restore-offer")).toContainText("2 favourite songs");
  await again.getByTestId("restore-yes").click();
  await expect(again.getByTestId("tv-status")).toBeVisible();
  await again.getByTestId("tab-search").click();
  await expect(again.getByTestId("favourite-row")).toHaveCount(2);

  // A different phone is offered nothing until it types a name that has a list, and can say no.
  const other = await party.emptyPhone("someone-else");
  await expect(other.getByTestId("name-input")).toBeVisible();
  await other.getByTestId("name-input").fill("alice");
  await other.getByTestId("name-submit").click();
  await expect(other.getByTestId("restore-offer")).toContainText("Welcome back, Alice");
  await other.getByTestId("restore-no").click();
  await expect(other.getByTestId("tv-status")).toBeVisible();
  await other.getByTestId("tab-search").click();
  await expect(other.getByTestId("favourites-empty")).toBeVisible();
});

test("browse by place: 香港 熱門 shelves, its singers, and Ready to sing", async ({ party }) => {
  const tv = await party.tv();
  await waitForTv(tv, (x) => x.stage.kind === "playing", "filler started");
  const phone = await party.phone("Alice");
  await phone.getByTestId("pause").click();
  await phone.getByTestId("tab-search").click();
  for (const box of ["hk", "tw", "cn", "jp", "kr", "west", "ready"]) {
    await expect(phone.getByTestId(`box-${box}`)).toBeVisible();
  }

  await phone.getByTestId("box-hk").click();
  const chart = phone.getByTestId("shelf").first();
  await expect(chart).toContainText("HK 熱門 Top 100");
  await expect(chart.getByTestId("online-result")).toHaveText([/測試之歌/]);
  await expect(chart.getByTestId("library-result")).toHaveText([/河流/]);
  await expect(chart).not.toContainText("NEON");
  await expect(phone.getByTestId("place-library")).toContainText("河流");
  await chart.getByTestId("online-result").getByTestId("queue-online").click();
  await phone.getByTestId("video-queue-best").click();
  await expect(phone.getByTestId("toast").filter({ hasText: "Queued “測試之歌”" })).toBeVisible();

  await phone.getByTestId("singer").filter({ hasText: "測試歌手" }).click();
  await expect(phone.getByTestId("artist-page")).toContainText("測試歌手");
  await expect(phone.getByTestId("place-setter")).toHaveCount(0, { timeout: 1000 });
  await phone.getByTestId("artist-back").click();
  await expect(phone.getByTestId("place-page")).toBeVisible();
  await phone.getByTestId("place-back").click();

  await phone.getByTestId("box-ready").click();
  await expect(phone.getByTestId("library-result")).toHaveCount(3);
});

test("the control page corrects where a singer is from", async ({ party }) => {
  const control = await party.control("Host");
  await control.getByTestId("box-hk").click();
  await expect(control.getByTestId("shelf").first()).toContainText("測試之歌");
  await control.getByTestId("singer").filter({ hasText: "測試歌手" }).click();
  await expect(control.getByTestId("place-select")).toHaveValue("hk");
  await control.getByTestId("place-select").selectOption("tw");
  await expect(control.getByTestId("place-status")).toHaveText("Saved");
  await control.getByTestId("artist-back").click();
  await control.getByTestId("place-back").click();
  await control.getByTestId("box-hk").click();
  await expect(control.getByTestId("shelf").first()).toContainText("河流");
  await expect(control.getByTestId("shelf").first()).not.toContainText("測試之歌");
  await control.getByTestId("place-back").click();
  await control.getByTestId("box-tw").click();
  await expect(control.getByTestId("singers")).toContainText("測試歌手");
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

test("two phones and the TV always agree on the vocal and the key", async ({ party }) => {
  const tv = await party.tv();
  await waitForTv(tv, (x) => x.stage.kind === "playing", "filler started");
  const alice = await party.phone("Alice");
  const bob = await party.phone("Bob");
  await alice.getByTestId("pause").click();
  await waitForTv(tv, (x) => x.paused, "paused");
  const agree = async (pct: string, gain: number, key: string, semitones: number): Promise<void> => {
    for (const phone of [alice, bob]) {
      await expect(phone.getByTestId("vocal-value")).toHaveText(new RegExp(pct), { timeout: 2000 });
      await expect(phone.getByTestId("key-value")).toHaveText(key, { timeout: 2000 });
    }
    await waitForTv(tv, (x) => Math.abs(x.vocalGain - gain) < 0.001 && x.semitones === semitones, `TV ${pct} ${key}`);
  };

  await alice.getByTestId("vocal-slider").fill("70");
  await agree("70%", 0.7, "0", 0);

  // Bob's finger lands on the slider and the browser cancels the touch (it became a scroll), so no pointerup.
  // Before the fix Bob's slider froze on its own value and later sent it, overriding everyone else.
  const slider = bob.getByTestId("vocal-slider");
  await slider.dispatchEvent("pointerdown", { pointerType: "touch" });
  await slider.fill("20");
  await slider.dispatchEvent("pointercancel", { pointerType: "touch" });
  await agree("20%", 0.2, "0", 0);
  await alice.getByTestId("vocal-slider").fill("50");
  await agree("50%", 0.5, "0", 0);

  // The switch restores the server's level on every phone, not each phone's own memory.
  await bob.getByTestId("vocal-toggle").click();
  await agree("Off", 0, "0", 0);
  await alice.getByTestId("vocal-toggle").click();
  await agree("50%", 0.5, "0", 0);

  // Key presses from both phones are steps, so three presses land on +3 everywhere.
  await alice.getByTestId("key-up").click();
  await bob.getByTestId("key-up").click();
  await alice.getByTestId("key-up").click();
  await agree("50%", 0.5, "+3", 3);
  await bob.getByTestId("key-reset").click();
  await agree("50%", 0.5, "0", 0);
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
