const { defineConfig } = require("@playwright/test");

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
      command: "python3 tests/e2e/mock_api_server.py",
      url: "http://127.0.0.1:8000/monitor/overview",
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
