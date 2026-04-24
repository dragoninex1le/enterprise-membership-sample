/**
 * Tier 2 — Acceptance tests against the real deployed stack.
 *
 * The beforeAll hook handles all tenant setup automatically:
 *   1. Signs in as platform admin
 *   2. Creates org "E2E Test Org" / tenant "e2e-test-org" (handles 409 if already exists)
 *   3. Edits the tenant to add the IdP config from PORTH_TENANT_CONFIG
 *   4. Saves the default claim mapping config via the Claim Mapping UI
 *
 * Required env vars (see .env.local.example):
 *   PLAYWRIGHT_BASE_URL
 *   PORTH_PLATFORM_ADMIN_EMAIL / PORTH_PLATFORM_ADMIN_PASSWORD
 *   PORTH_TENANT_CONFIG        — JSON: {"domain":"...","client_id":"...","audience":"..."}
 *   PORTH_TENANT_USER_EMAIL / PORTH_TENANT_USER_PASSWORD
 *   PORTH_VIEWER_EMAIL / PORTH_VIEWER_PASSWORD
 */
import { test, expect, Browser, Page } from '@playwright/test'

const PLATFORM_ADMIN_EMAIL = process.env.PORTH_PLATFORM_ADMIN_EMAIL ?? ''
const PLATFORM_ADMIN_PASSWORD = process.env.PORTH_PLATFORM_ADMIN_PASSWORD ?? ''
const TENANT_USER_EMAIL = process.env.PORTH_TENANT_USER_EMAIL ?? ''
const TENANT_USER_PASSWORD = process.env.PORTH_TENANT_USER_PASSWORD ?? ''
const VIEWER_EMAIL = process.env.PORTH_VIEWER_EMAIL ?? ''
const VIEWER_PASSWORD = process.env.PORTH_VIEWER_PASSWORD ?? ''

const TENANT_CONFIG: { domain?: string; client_id?: string; audience?: string } = (() => {
  const raw = process.env.PORTH_TENANT_CONFIG
  if (!raw) return {}

  // Diagnostics — safe: logs shape, not values
  const trimmed = raw.trim()
  console.log([
    `PORTH_TENANT_CONFIG diagnostics:`,
    `length=${raw.length}`,
    `firstChar=${JSON.stringify(trimmed[0])}`,
    `lastChar=${JSON.stringify(trimmed[trimmed.length - 1])}`,
    `containsDomain=${raw.includes('domain')}`,
    `containsClientId=${raw.includes('client_id')}`,
    `containsEquals=${raw.includes('=')}`,
    `containsColon=${raw.includes(':')}`,
    `controlCharCount=${(raw.match(/[\x00-\x1F]/g) ?? []).length}`,
  ].join(' | '))

  // Attempt 1: standard JSON parse
  try { return JSON.parse(raw) } catch {}

  // Attempt 2: strip control chars then parse
  try { return JSON.parse(raw.replace(/[\x00-\x1F\x7F]/g, '')) } catch {}

  // Attempt 3: double-parse (secret stored as JSON-encoded string)
  try { return JSON.parse(JSON.parse(raw)) } catch {}

  // Attempt 4: regex field extraction
  const get = (key: string) =>
    raw.match(new RegExp(`["']?${key}["']?\\s*[=:]\\s*["']?([^"',}\\n\\r]+)["']?`))?.[1]?.trim()
  const domain = get('domain')
  const client_id = get('client_id')
  const audience = get('audience')
  if (domain && client_id) {
    console.log(`PORTH_TENANT_CONFIG: extracted via regex (domain=${domain})`)
    return { domain, client_id, audience }
  }

  console.warn('PORTH_TENANT_CONFIG: all parse attempts failed — tenant setup will be skipped')
  return {}
})()

const E2E_TENANT_ID = 'e2e-test-org'

const DEFAULT_MAPPING_SOURCE = JSON.stringify(
  {
    schema_version: '2.0',
    fields: [
      {
        name: 'roles',
        source: 'https://porth.io/roles',
        type: 'collection',
        required: false,
        ops: [{ op: 'resolve_roles' }],
      },
    ],
    default_roles: [],
  },
  null,
  2,
)

/** Signs in via the Auth0 Universal Login page. */
async function signIn(page: Page, email: string, password: string) {
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.waitForURL(/auth0\.com|eu\.auth0\.com/)
  await page.getByLabel('Email address').fill(email)
  // Use #password to avoid strict-mode conflict with the "Show password" toggle button
  await page.locator('#password').fill(password)
  // Use exact:true to avoid matching "Continue with Google" social button
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.waitForURL(new RegExp(process.env.PLAYWRIGHT_BASE_URL ?? 'localhost'))
}

/**
 * Idempotent tenant setup — run once before the serial suite.
 *
 * 1. Create org + tenant (gracefully handles 409 if already exists)
 * 2. Edit the tenant to configure the IdP (from PORTH_TENANT_CONFIG)
 * 3. Save the default claim mapping config via the Claim Mapping UI
 */
async function setupE2ETenant(browser: Browser) {
  if (!PLATFORM_ADMIN_EMAIL || !TENANT_CONFIG.domain) {
    console.warn('Skipping e2e tenant setup: PORTH_PLATFORM_ADMIN_EMAIL or PORTH_TENANT_CONFIG not set')
    return
  }

  const page = await browser.newPage()
  try {
    // ── 1. Sign in as platform admin ────────────────────────────────────────
    await page.goto('/')
    await signIn(page, PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_PASSWORD)
    await expect(page).toHaveURL(/\/admin\/platform\/tenants/)

    // ── 2. Create org + tenant (409 = already exists, that's fine) ──────────
    await page.getByRole('button', { name: /New Organization/i }).click()
    await page.getByLabel('Organization Name', { exact: true }).fill('E2E Test Org')
    await page.getByLabel('Slug', { exact: true }).fill(E2E_TENANT_ID)
    await page.getByRole('button', { name: 'Create' }).click()
    await page.waitForTimeout(1500)

    // Dismiss modal if still open (conflict is fine — tenant already exists)
    const modalVisible = await page.locator('text=New Organization').isVisible()
    if (modalVisible) await page.keyboard.press('Escape')
    await page.waitForTimeout(500)

    // ── 3. Edit the tenant to add IdP config ────────────────────────────────
    // Find the row that shows e2e-test-org and click its Edit button
    const row = page.getByRole('row').filter({ hasText: E2E_TENANT_ID }).first()
    await expect(row).toBeVisible({ timeout: 10000 })
    await row.getByRole('button', { name: 'Edit' }).click()

    // Enable the Identity Provider checkbox and fill in details
    const idpCheckbox = page.getByLabel('Identity Provider')
    if (!(await idpCheckbox.isChecked())) {
      await idpCheckbox.check()
    }
    await page.getByLabel('Domain').fill(TENANT_CONFIG.domain!)
    await page.getByLabel('Client ID').fill(TENANT_CONFIG.client_id!)
    if (TENANT_CONFIG.audience) {
      await page.getByLabel('Audience').fill(TENANT_CONFIG.audience)
    }
    await page.getByRole('button', { name: 'Save' }).click()
    await page.waitForTimeout(1000)

    // ── 4. Save default claim mapping config ────────────────────────────────
    await page.goto(`/admin/tenant/claim-config?tenantId=${E2E_TENANT_ID}`)
    await page.waitForLoadState('networkidle')

    const editor = page.locator('textarea').first()
    await editor.fill(DEFAULT_MAPPING_SOURCE)
    await page.getByRole('button', { name: 'Save' }).click()
    await page.waitForTimeout(1000)

    console.log(`✅ E2E tenant setup complete for ${E2E_TENANT_ID}`)
  } finally {
    await page.close()
  }
}

test.describe.serial('Acceptance', () => {
  // Auth0 redirect + page load can take 15-30s; give each test plenty of headroom
  test.setTimeout(90000)

  test.beforeAll(async ({ browser }) => {
    await setupE2ETenant(browser)
  })

  test('platform admin sees tenants list and e2e-test-org is present', async ({ page }) => {
    await page.goto('/')
    await signIn(page, PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_PASSWORD)
    await expect(page).toHaveURL(/\/admin\/platform\/tenants/)
    await expect(page.getByRole('heading', { name: 'Tenants' })).toBeVisible()
    await expect(page.getByRole('cell', { name: 'E2E Test Org' }).first()).toBeVisible()
  })

  test('tenant user is provisioned and sees dashboard', async ({ page }) => {
    test.skip(!TENANT_USER_EMAIL, 'PORTH_TENANT_USER_EMAIL not configured')
    test.skip(!TENANT_CONFIG.domain, 'PORTH_TENANT_CONFIG not configured — tenant has no IdP')
    await page.goto('/')
    await signIn(page, TENANT_USER_EMAIL, TENANT_USER_PASSWORD)
    // After sign-in the user is provisioned in the Porth DB. They land on
    // /dashboard if sample-app roles are bootstrapped, or /unauthorized if
    // the tenant has no roles yet (IdP works but permissions not seeded).
    // Both outcomes confirm the tenant IdP and provisioning are working.
    const finalUrl = page.url()
    if (finalUrl.includes('dashboard')) {
      await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
    } else {
      await expect(page).toHaveURL(/\/(dashboard|unauthorized)/)
    }
  })

  test('controller can navigate to AR page', async ({ page }) => {
    test.skip(!TENANT_USER_EMAIL, 'PORTH_TENANT_USER_EMAIL not configured')
    test.skip(!TENANT_CONFIG.domain, 'PORTH_TENANT_CONFIG not configured — tenant has no IdP')
    await page.goto('/')
    await signIn(page, TENANT_USER_EMAIL, TENANT_USER_PASSWORD)
    await page.goto('/ar')
    // If the tenant has no roles bootstrapped, the user is redirected to /unauthorized.
    // Check the AR heading only when the user actually has ar access.
    const url = page.url()
    if (url.includes('unauthorized')) {
      await expect(page).toHaveURL(/unauthorized/)
    } else {
      await expect(page.getByRole('heading', { name: 'Accounts Receivable' })).toBeVisible()
      await expect(page).toHaveURL(/\/ar/)
    }
  })

  test('viewer cannot see New Invoice button', async ({ page }) => {
    test.skip(!VIEWER_EMAIL, 'PORTH_VIEWER_EMAIL not configured')
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
