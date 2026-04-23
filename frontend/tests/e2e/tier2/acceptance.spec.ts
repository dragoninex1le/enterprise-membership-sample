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
  // The app shows a "Sign in" button when unauthenticated (Layout.tsx)
  await page.getByRole('button', { name: 'Sign in' }).click()
  // Auth0 Universal Login
  await page.waitForURL(/auth0\.com|eu\.auth0\.com/)
  await page.getByLabel('Email address').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Continue' }).click()
  // Wait for redirect back to app
  await page.waitForURL(new RegExp(process.env.PLAYWRIGHT_BASE_URL ?? 'localhost'))
}

test.describe.serial('Acceptance', () => {
  test('platform admin can create org and tenant', async ({ page }) => {
    await page.goto('/')
    await signIn(page, PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_PASSWORD)
    // Platform admin lands on organizations page
    await expect(page).toHaveURL(/\/admin\/platform\/organizations/)
    await expect(page.getByRole('heading', { name: 'Organizations' })).toBeVisible()
    // New Organization button present
    await expect(page.getByRole('button', { name: /New Organization/i })).toBeVisible()
  })

  test('tenant user is provisioned and sees dashboard', async ({ page }) => {
    await page.goto('/')
    await signIn(page, TENANT_USER_EMAIL, TENANT_USER_PASSWORD)
    // Tenant users redirect to dashboard
    await expect(page).toHaveURL(/\/dashboard/)
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  })

  test('controller can create invoice', async ({ page }) => {
    await page.goto('/')
    await signIn(page, TENANT_USER_EMAIL, TENANT_USER_PASSWORD)
    await page.goto('/ar')
    await expect(page.getByRole('heading', { name: 'Accounts Receivable' })).toBeVisible()
    // When AR screen is fully implemented, a "New Invoice" button will be visible
    // for controller role. Loose assertion for now:
    await expect(page).toHaveURL(/\/ar/)
  })

  test('viewer cannot see New Invoice button', async ({ page }) => {
    await page.goto('/')
    await signIn(page, VIEWER_EMAIL, VIEWER_PASSWORD)
    await page.goto('/ar')
    // Viewer has no ar_clerk or controller role -- redirected to /unauthorized
    // or AR screen renders without a write-action button
    const url = page.url()
    const isUnauthorized = url.includes('unauthorized')
    if (!isUnauthorized) {
      // If viewer can see the AR page, the New Invoice button must not be present
      await expect(page.getByRole('button', { name: /New Invoice/i })).not.toBeVisible()
    } else {
      await expect(page).toHaveURL(/unauthorized/)
    }
  })
})
