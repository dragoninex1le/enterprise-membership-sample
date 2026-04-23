/**
 * Tier 2 -- Acceptance tests against the real deployed stack.
 *
 * Tests 2 and 3 are currently skipped pending manual bootstrap:
 *   1. Create org "E2E Test Org" (slug: e2e-test-org) + tenant "e2e-test-dev" via admin UI
 *      (Test 1 does this, but it needs to succeed first)
 *   2. Go to /admin/tenant/claim-config?tenantId=e2e-test-dev and save the default mapping JSON
 *   3. Log in once as the tenant user to provision their Porth record
 *   4. In User Management, assign the tenant user the "controller" role
 *   Once complete, remove the test.skip calls from tests 2 and 3.
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
  // Use exact:true to avoid matching "Continue with Google" social button
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.waitForURL(new RegExp(process.env.PLAYWRIGHT_BASE_URL ?? 'localhost'))
}

test.describe.serial('Acceptance', () => {
  // Auth0 redirect + page load can take 15-30s; give each test plenty of headroom
  test.setTimeout(90000)

  test('platform admin can create org and tenant', async ({ page }) => {
    await page.goto('/')
    await signIn(page, PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_PASSWORD)
    await expect(page).toHaveURL(/\/admin\/platform\/organizations/)
    await expect(page.getByRole('heading', { name: 'Organizations' })).toBeVisible()

    // Open New Organization modal and fill all required fields
    await page.getByRole('button', { name: /New Organization/i }).click()
    // exact:true required — "Name" would also match the "Display Name" input
    await page.getByLabel('Name', { exact: true }).fill('E2E Test Org')
    await page.getByLabel('Slug', { exact: true }).fill('e2e-test-org')
    await page.getByLabel('Tenant ID', { exact: true }).fill('e2e-test-dev')
    await page.getByLabel('Display Name', { exact: true }).fill('E2E Test Dev')
    await page.getByRole('button', { name: 'Create' }).click()

    // Accept either success (modal closes, org in list) or 409 conflict (already exists from prev run)
    await page.waitForTimeout(1500)
    const modalVisible = await page.locator('text=New Organization').isVisible()
    if (modalVisible) {
      const errorText = await page.locator('[class*="red"]').textContent() ?? ''
      expect(errorText.toLowerCase()).toMatch(/already|exist|conflict/)
    } else {
      await expect(page.getByText('E2E Test Org')).toBeVisible()
    }
  })

  test('tenant user is provisioned and sees dashboard', async ({ page }) => {
    // Requires: claim mapping saved for e2e-test-dev, tenant user logged in once, controller role assigned
    // Remove this skip once the pre-flight checklist above is complete.
    test.skip(true, 'Pending manual bootstrap — see checklist in file header')
    await page.goto('/')
    await signIn(page, TENANT_USER_EMAIL, TENANT_USER_PASSWORD)
    await expect(page).toHaveURL(/\/dashboard/)
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  })

  test('controller can navigate to AR page', async ({ page }) => {
    // Depends on test 2 passing (tenant user provisioned with controller role)
    // Remove this skip once the pre-flight checklist above is complete.
    test.skip(true, 'Pending manual bootstrap — see checklist in file header')
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
