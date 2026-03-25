const { defineConfig } = require("@playwright/test");

const mockApiPort = process.env.MOCK_API_PORT || "18000";

module.exports = defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    viewport: { width: 1440, height: 1080 },
  },
  webServer: [
    {
      command: `MOCK_API_PORT=${mockApiPort} python3 tests/e2e/mock_api_server.py`,
      url: `http://127.0.0.1:${mockApiPort}/monitor/overview`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: "python3 -m http.server 4173 --bind 127.0.0.1 --directory apps/web",
      url: "http://127.0.0.1:4173/",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
