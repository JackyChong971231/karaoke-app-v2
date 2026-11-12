import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  // Every test boots its own fake-world server, and one laptop plays audio, so tests run one at a time.
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    channel: "msedge",
    launchOptions: { args: ["--autoplay-policy=no-user-gesture-required"] },
    trace: "retain-on-failure",
  },
});
