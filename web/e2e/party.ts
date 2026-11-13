import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { openSync } from "node:fs";
import { networkInterfaces, tmpdir } from "node:os";
import { createServer } from "node:net";
import { resolve } from "node:path";
import { test as base, expect, type Browser, type Page } from "@playwright/test";

const SERVER_DIR = resolve(import.meta.dirname, "../../server");

export interface TvProbe {
  loadedSongId: string | null;
  playId: number | null;
  paused: boolean;
  semitones: number;
  vocalGain: number;
  audible: number;
  display: number;
  videoTime: number;
  stage: { kind: "idle" | "loading" | "playing" | "failed" };
  slots: { line: number | null; text: string; fills: number[] }[];
}

function freePort(): Promise<number> {
  return new Promise((done, fail) => {
    const srv = createServer();
    srv.listen(0, () => {
      const address = srv.address();
      srv.close(() => (typeof address === "object" && address !== null ? done(address.port) : fail(new Error("no port"))));
    });
  });
}

/** Real phones reach the laptop by its LAN address over plain http, which is not a secure context
 * (no crypto.randomUUID, clipboard, and similar). localhost is secure, so phones must not use it. */
function lanAddress(): string {
  const v4 = Object.values(networkInterfaces()).flat().find((a) => a?.family === "IPv4" && !a.internal);
  if (v4 === undefined) throw new Error("no LAN IPv4 address: phone tests need one to load the page insecurely");
  return v4.address;
}

function uvCommand(): string {
  const local = process.env.LOCALAPPDATA;
  const winget = local === undefined ? null : resolve(local, "Microsoft/WinGet/Links/uv.exe");
  const found = spawnSync(process.platform === "win32" ? "where" : "which", ["uv"], { encoding: "utf8" });
  if (found.status === 0) return "uv";
  return winget ?? "uv";
}

async function startServer(): Promise<{ url: string; proc: ChildProcess }> {
  const port = await freePort();
  // The server log goes to a file: an unread pipe fills up and blocks the server mid-test.
  const log = openSync(resolve(tmpdir(), `karaoke-fake-${String(port)}.log`), "w");
  const proc = spawn(
    uvCommand(),
    ["run", "karaoke", "serve", "--world", "fake", "--no-open-tv", "--port", String(port), "--fake-delay", "0.3"],
    { cwd: SERVER_DIR, stdio: ["ignore", log, log], windowsHide: true },
  );
  const url = `http://localhost:${String(port)}`;
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (proc.exitCode !== null) throw new Error(`fake server exited with ${String(proc.exitCode)}`);
    try {
      if ((await fetch(`${url}/test/state`)).ok) return { url, proc };
    } catch {
      // not listening yet
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("fake server did not start in 60 s");
}

function stopServer(proc: ChildProcess): void {
  if (proc.pid === undefined) return;
  if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(proc.pid), "/T", "/F"]);
  else proc.kill();
}

export class Party {
  constructor(
    readonly url: string,
    private readonly browser: Browser,
    readonly phoneUrl = url.replace("localhost", lanAddress()),
  ) {}

  /** On a 1920x1080 screen. A smaller `window` is a browser window rather than a kiosk filling the screen. */
  async tv(window = { width: 1920, height: 1080 }): Promise<Page> {
    const ctx = await this.browser.newContext({ viewport: window, screen: { width: 1920, height: 1080 } });
    const page = await ctx.newPage();
    await page.goto(`${this.url}/tv`);
    return page;
  }

  /** The laptop control page: a mouse, a wide window, and the same controls as a phone. */
  async control(name: string): Promise<Page> {
    const ctx = await this.browser.newContext({ viewport: { width: 1600, height: 900 } });
    const page = await ctx.newPage();
    await page.goto(`${this.url}/control`);
    await page.getByTestId("name-input").fill(name);
    await page.getByTestId("name-submit").click();
    await expect(page.getByTestId("tv-status")).toBeVisible();
    return page;
  }

  /** A fresh browser context is a new browser. A singer is a phone's Wi-Fi address, and every test phone runs on
   *  this computer, so the fake world's test cookie stands in for the address: `device` defaults to the name.
   *  Two pages with the same `device` are two browsers on one phone. */
  async phone(name: string, device = name): Promise<Page> {
    const page = await this.emptyPhone(device);
    await page.getByTestId("name-input").fill(name);
    await page.getByTestId("name-submit").click();
    await expect(page.getByTestId("tv-status")).toBeVisible();
    return page;
  }

  /** A phone whose browser has nothing saved, as after the laptop's address changed. Stops at the first screen. */
  async emptyPhone(device: string): Promise<Page> {
    const ctx = await this.browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 2,
      isMobile: true,
      hasTouch: true,
    });
    await ctx.addCookies([{ name: "karaoke-test-device", value: device, url: this.phoneUrl }]);
    const page = await ctx.newPage();
    await page.goto(`${this.phoneUrl}/`);
    expect(await page.evaluate(() => window.isSecureContext), "phone page must load like a real phone").toBe(false);
    return page;
  }
}

export async function probe(tv: Page): Promise<TvProbe> {
  return tv.evaluate(() => window.__karaokeTv?.probe() as TvProbe);
}

export async function waitForTv(tv: Page, pred: (p: TvProbe) => boolean, label: string): Promise<TvProbe> {
  let last: TvProbe | null = null;
  await expect
    .poll(async () => {
      last = await probe(tv);
      return pred(last);
    }, { message: label, timeout: 20_000, intervals: [100] })
    .toBe(true)
    .catch((e: unknown) => {
      throw new Error(`${label}; last probe: ${JSON.stringify(last)}`, { cause: e });
    });
  if (last === null) throw new Error(label);
  return last;
}

/** Queue a library song by searching its exact title. */
export async function queueLibrary(phone: Page, title: string): Promise<void> {
  // The control page shows search beside the other screens, with no tabs.
  if ((await phone.getByTestId("tab-search").count()) > 0) await phone.getByTestId("tab-search").click();
  await phone.getByTestId("search-input").fill(title);
  const row = phone.getByTestId("library-result").filter({ hasText: title }).first();
  await row.getByTestId("queue-library").click();
  await expect(phone.getByTestId("toast").filter({ hasText: `Queued “${title}”` })).toBeVisible();
}

export const test = base.extend<{ party: Party }>({
  party: async ({ browser }, use) => {
    const { url, proc } = await startServer();
    try {
      await use(new Party(url, browser));
    } finally {
      stopServer(proc);
    }
  },
});

export { expect };

declare global {
  interface Window {
    __karaokeTv?: { probe(): unknown };
  }
}
