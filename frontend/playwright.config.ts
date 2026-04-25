import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  // Tier 2 tests run against the live deployed stack where Auth0 redirects,
  // Lambda cold starts, and DynamoDB provisioning can each add 3-8 seconds.
  // Raise the assertion timeout from the 5-second default so that
  // expect(page).toHaveURL(…) doesn't race ahead of the redirect.
  expect: { timeout: 20000 },
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    env: {
      VITE_E2E_AUTH: 'true',
      VITE_API_BASE_URL: 'http://localhost:5173',
      VITE_DEV_TENANT_ID: 'test-tenant',
    },
  },
})
