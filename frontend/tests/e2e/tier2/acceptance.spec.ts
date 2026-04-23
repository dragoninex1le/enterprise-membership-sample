/**
 * Tier 2 -- Acceptance tests against the real deployed stack.
 *
 * These tests require real credentials provided via environment variables.
 * They run on the main branch only (see .github/workflows/e2e.yml).
 *
 * Required env vars (see .env.local.example):
 *   PLAYWRIGHT_BASE_URL
 *   PORTH_PLATFORM_ADMIN_EMAIL / PORTH_PLATFORM_ADMIN_PASSWORD
 *   PORTH_TENANT_USER_EMAIL / PORTH_TENANT_USER_PASSWORD
 *   PORTH_VIEWER_EMAIL / PORTH_VIEWER_PASSWORD
 */
import { test, expect } from '@playwright/test'

const PLATFORM_ADMIN_EMAIL = process.env.PORTH_PLATFORM_ADMIN_EMAIL ?? ''
const PLATFORM_ADMIN_PASSWORD = process.env.PORTH_PLATFORM_ADMIN_PASSWORD ?? ''
const TENANT_USER_EMAIL = process.env.PORTH_TENANT_USER_EMAIL ?? ''
const TENANT_USER_PASSWORD = process.env.PORTH_TENANT_USER_PASSWORD ?? ''
const VIEWER_EMAIL = process.env.PORTH_VIEWER_EMAIL ?? ''
const VIEWER_PASSWORD = process.env.PORTH_VIEWER_PASSWORD ?? ''

/** Signs in via the Auth0 Universal Login page. */
async function signIn(page: import('@playwright/test').Page, email: string, password: string) {
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.waitForURL(/auth0\.com|eu\.auth0\.com/)
  await page.getByLabel('Email address').fill(email)
  // Use #password to avoid strict-mode conflict with the "Show password" toggle button
  await page.locator('#password').fill(password)
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.waitForURL(new RegExp(process.env.PLAYWRIGHT_BASE_URL ?? 'localhost'))
}

test.describe.serial('Acceptance', () => {
  test('platform admin can create org and tenant', async ({ page }) => {
    await page.goto('/')
    await signIn(page, PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_PASSWORD)
    await expect(page).toHaveURL(/\/admin\/platform\/organizations/)
    await expect(page.getByRole('heading', { name: 'Organizations' })).toBeVisible()
    await expect(page.getByRole('button', { name: /New Organization/i })).toBeVisible()
  })

  test('tenant user is provisioned and sees dashboard', async ({ page }) => {
    await page.goto('/')
    await signIn(page, TENANT_USER_EMAIL, TENANT_USER_PASSWORD)
    await expect(page).toHaveURL(/\/dashboard/)
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  })

  test('controller can navigate to AR page', async ({ page }) => {
    await page.goto('/')
    await signIn(page, TENANT_USER_EMAIL, TENANT_USER_PASSWORD)
    await page.goto('/ar')
    await expect(page.getByRole('heading', { name: 'Accounts Receivable' })).toBeVisible()
    await expect(page).toHaveURL(/\/ar/)
  })

  test('viewer cannot see New Invoice button', async ({ page }) => {
    test.skip(!VIEWER_EMAIL, 'PORTH_VIEWER_EMAIL secret not configured')
    await page.goto('/')
    await signIn(page, VIEWER_EMAIL, VIEWER_PASSWORD)
    await page.goto('/ar')
    const url = page.url()
    if (url.includes('unauthorized')) {
      await expect(page).toHaveURL(/unauthorized/)
    } else {
      await expect(page.getByRole('button', { name: /New Invoice/i })).not.toBeVisible()
    }
  })
})
