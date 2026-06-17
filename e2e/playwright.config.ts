import { defineConfig, devices } from '@playwright/test';

// E2E drives the FULL app on the dummy (plan.md §21): the backend serves the
// pre-built Angular frontend, so `make build` (or the CI build step) must run first.
// No hardware — the dummy device is the default, and synthesis is deterministic.
const PORT = 8123;

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'on-first-retry',
  },
  webServer: {
    // Use the repo-root venv's python to run the backend, which serves frontend/dist.
    command: `../.venv/bin/python -m uvicorn app.main:app --port ${PORT}`,
    cwd: '../backend',
    url: `http://localhost:${PORT}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
