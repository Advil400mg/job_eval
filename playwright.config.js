import { existsSync } from 'node:fs';
import { defineConfig, devices } from '@playwright/test';

const python = process.env.JEV_E2E_PYTHON ||
  (existsSync('.venv/bin/python') ? '.venv/bin/python' : 'python');

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: /.*\.spec\.js/,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['line'], ['html', { open: 'never' }]] : 'line',
  use: {
    baseURL: 'http://127.0.0.1:8769',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: `${python} tests/e2e/serve.py`,
    url: 'http://127.0.0.1:8769/healthz',
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
