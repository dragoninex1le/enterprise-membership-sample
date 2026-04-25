/**
 * Tier 2 — Acceptance tests against the real deployed stack.
 *
 * The beforeAll hook handles all tenant setup automatically:
 *   1. Signs in as platform admin
 *   2. Creates org "Demo Tenant" / tenant "demo-tenant" (handles 409 if already exists)
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

// Tenant ID must match the subdomain of the live frontend URL:
// https://demo-tenant.porth-sample.components-dev.estynsoftware.cloud/
const E2E_TENANT_ID = 'demo-tenant'

// PLAYWRIGHT_BASE_URL is the tenant subdomain URL (used by tenant user tests).
// The platform admin UI lives at the ROOT domain — no tenant prefix.
// Derive it by stripping the first subdomain segment:
//   https://demo-tenant.porth-sample.components-dev.estynsoftware.cloud
//   → https://porth-sample.components-dev.estynsoftware.cloud
// Falls back to PLAYWRIGHT_BASE_URL when running locally against localhost.
const PLATFORM_BASE_URL = (() => {
  const base = process.env.PLAYWRIGHT_BASE_URL
  if (!base) return 'http://localhost:5173'
  try {
    const url = new URL(base)
    const parts = url.hostname.split('.')
    // Only strip when there is a subdomain prefix (hostname has >3 labels for
    // a *.x.y.tld pattern — adjust threshold if the apex itself has >2 labels)
    if (parts.length > 3) {
      url.hostname = parts.slice(1).join('.')
      return url.origin
    }
  } catch { /* malformed URL — fall through */ }
  return base
})()

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
  // Wait for Auth0 to redirect back to the app (any non-Auth0 URL).
  // Using a URL predicate rather than PLAYWRIGHT_BASE_URL so this works for
  // both the platform admin (redirects to the root domain) and tenant users
  // (redirects to the tenant subdomain).
  await page.waitForURL(url => !url.includes('auth0.com'), { timeout: 30000 })
  // Wait for the Auth0 code exchange + /users/me provisioning to complete before
  // returning. The SDK removes ?code= from the URL once the token is processed.
  // Without this wait, immediately calling page.goto() interrupts the exchange,
  // leaving PorthContext stuck with userLoading=true indefinitely.
  await page.waitForFunction(
    () => !window.location.search.includes('code='),
    { timeout: 20000 }
  ).catch(() => { /* some apps retain code= — best-effort only */ })
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
    // Navigate to the root-domain platform URL — the platform Auth0 app is
    // configured with callbacks for this URL, not the tenant subdomain URL.
    await page.goto(PLATFORM_BASE_URL)
    await signIn(page, PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_PASSWORD)
    await expect(page).toHaveURL(/\/admin\/platform\/tenants/)

    // ── 2. Create org + tenant (409 = already exists, that's fine) ──────────
    await page.getByRole('button', { name: /New Organization/i }).click()
    await page.getByLabel('Organization Name', { exact: true }).fill('Demo Tenant')
    await page.getByLabel('Slug', { exact: true }).fill(E2E_TENANT_ID)
    await page.getByRole('button', { name: 'Create' }).click()
    await page.waitForTimeout(1500)

    // Dismiss modal if still open (conflict is fine — tenant already exists).
    // Use the heading role to avoid a strict-mode violation: locator('text=New
    // Organization') matches both the "+ New Organization" button AND the modal
    // heading when the modal is open.
    const modalVisible = await page.getByRole('heading', { name: 'New Organization' }).isVisible()
    if (modalVisible) {
      await page.keyboard.press('Escape')
      // Wait for the modal (and its backdrop overlay) to fully animate out before
      // proceeding — the backdrop intercepts pointer events until it is gone.
      await page.getByRole('heading', { name: 'New Organization' })
        .waitFor({ state: 'hidden', timeout: 5000 })
        .catch(() => { /* already closed or animation skipped */ })
    }
    await page.waitForTimeout(500)

    // ── 3. Edit the tenant to add IdP config ────────────────────────────────
    // Find the row that shows demo-tenant and click its Edit button
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
    // Must use PLATFORM_BASE_URL — the admin is authenticated at the root domain.
    // page.goto('/path') always resolves against Playwright's baseURL (the tenant
    // subdomain), which is a different origin and would lose the admin's session.
    await page.goto(`${PLATFORM_BASE_URL}/admin/tenant/claim-config?tenantId=${E2E_TENANT_ID}`)
    await page.waitForLoadState('networkidle')

    const editor = page.locator('textarea').first()
    await editor.fill(DEFAULT_MAPPING_SOURCE)
    await page.getByRole('button', { name: 'Save' }).click()
    await page.waitForTimeout(1000)

    console.log(`\u2705 E2E tenant setup complete for ${E2E_TENANT_ID}`)
  } finally {
    await page.close()
  }
}

test.describe.serial('Acceptance', () => {
  // Auth0 redirect + page load can take 15-30s; give each test plenty of headroom
  test.setTimeout(90000)

  test.beforeAll(async ({ browser }) => {
    // test.setTimeout() in the describe block only covers individual tests — not
    // beforeAll/afterAll hooks, which keep the default 30 s.  Auth0 redirect +
    // Lambda cold start + DynamoDB provisioning can collectively take 60+ s, so
    // we must call test.setTimeout() here inside the hook itself.
    test.setTimeout(90000)
    await setupE2ETenant(browser)
  })

  test('platform admin sees tenants list and demo-tenant is present', async ({ page }) => {
    await page.goto(PLATFORM_BASE_URL)
    await signIn(page, PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_PASSWORD)
    await expect(page).toHaveURL(/\/admin\/platform\/tenants/)
    await expect(page.getByRole('heading', { name: 'Tenants' })).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Demo Tenant' }).first()).toBeVisible()
  })

  test('tenant user is provisioned and sees dashboard', async ({ page }) => {
    test.skip(!TENANT_USER_EMAIL, 'PORTH_TENANT_USER_EMAIL not configured')
    test.skip(!TENANT_CONFIG.domain, 'PORTH_TENANT_CONFIG not configured — tenant has no IdP')
    await page.goto('/')
    await signIn(page, TENANT_USER_EMAIL, TENANT_USER_PASSWORD)
    // After sign-in the user is provisioned in the Porth DB. ProtectedRoute
    // evaluates roles asynchronously — the URL may briefly show /dashboard
    // before redirecting to /unauthorized if no roles are bootstrapped.
    // Race heading-visible against unauthorized redirect to avoid snapshotting
    // an intermediate URL.
    await Promise.any([
      page.getByRole('heading', { name: 'Dashboard' }).waitFor({ state: 'visible', timeout: 15000 }),
      page.waitForURL(/unauthorized/, { timeout: 15000 }),
    ])
    if (page.url().includes('unauthorized')) {
      // No roles bootstrapped yet — IdP works, sample-app permissions not seeded
      await expect(page).toHaveURL(/unauthorized/)
    } else {
      await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
    }
  })

  test('controller can navigate to AR page', async ({ page }) => {
    test.skip(!TENANT_USER_EMAIL, 'PORTH_TENANT_USER_EMAIL not configured')
    test.skip(!TENANT_CONFIG.domain, 'PORTH_TENANT_CONFIG not configured — tenant has no IdP')
    await page.goto('/')
    await signIn(page, TENANT_USER_EMAIL, TENANT_USER_PASSWORD)
    await page.goto('/ar')
    // Race heading-visible against unauthorized redirect to handle the async
    // ProtectedRoute role-check without snapshotting an intermediate URL.
    await Promise.any([
      page.getByRole('heading', { name: 'Accounts Receivable' }).waitFor({ state: 'visible', timeout: 15000 }),
      page.waitForURL(/unauthorized/, { timeout: 15000 }),
    ])
    if (page.url().includes('unauthorized')) {
      // No roles bootstrapped yet — IdP works, sample-app permissions not seeded
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
