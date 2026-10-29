import { defineConfig, devices } from '@playwright/test';

const externalServer = process.env.E2E_BASE_URL;
const preview = process.env.E2E_PREVIEW === '1';
const basePath = `${(process.env.BASE_PATH || '/').replace(/\/$/, '')}/`;
const baseURL = externalServer
  ? `${externalServer.replace(/\/$/, '')}/`
  : new URL(basePath, 'http://127.0.0.1:4173').href;
export default defineConfig({
  testDir: './tests/browser',
  timeout: 45_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    channel: 'chrome',
    launchOptions: {
      args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
    },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chrome-desktop', use: { viewport: { width: 1440, height: 1050 } } },
    {
      name: 'chrome-mobile',
      use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium', channel: 'chrome' },
    },
  ],
  webServer: externalServer
    ? undefined
    : {
        command: preview
          ? 'node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 4173 --strictPort'
          : 'node scripts/prepare-data.mjs && node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173 --strictPort',
        url: baseURL,
        reuseExistingServer: !preview && !process.env.CI,
      },
});
