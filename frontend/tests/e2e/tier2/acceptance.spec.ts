/**
 * Tier 2 — Acceptance tests against the real deployed stack.
 *
 * The beforeAll hook handles all tenant setup automatically:
 *   1. Signs in as platform admin
 *   2. Creates org "Demo Corp" / tenant "demo-tenant" (handles 409 if already exists)
 *   3. Seeds sample-app permissions + roles (tenant-admin, controller) with source_key
 *   4. Patches the tenant IdP config via Porth API (PATCH /tenants/{id})
 *   5. Saves the default claim mapping config via the Porth API (POST /claim-mapping-configs/)
 *
 * Subsequent tests validate the full self-service flow:
 *   6. Platform admin sees organizations list with Demo Corp
 *   7. Platform admin assigns permissions to the controller role via Roles UI
 *   8. Controller user signs in and verifies access to the AR page
 *
 * WHY source_key matters:
 *   The Porth resolve_roles op builds an in-memory registry keyed by source_key.
 *   Roles without source_key are SKIPPED. If both tenant-admin and controller are
 *   created without source_key (the API default), no JWT claim can ever resolve to
 *   a Porth role and every user gets 401/unauthorized regardless of Auth0 roles.
 *
 * Navigation note — page.goto() is avoided after sign-in:
 *   Every full page reload resets the Auth0 SDK's in-memory token. The SDK
 *   then starts a silent-auth iframe check; with an active Auth0 session the
 *   postMessage from auth0.com hangs indefinitely in CI headless Chrome
 *   (isLoading stays true, the app shows a spinner forever).
 *
 *   Instead, after sign-in we let RootRedirect navigate via React Router
 *   (client-side, no reload). For pages with no sidebar link (Roles,
 *   ClaimMappingConfig) we trigger React Router by calling
 *   history.pushState + window.dispatchEvent(new PopStateEvent('popstate')).
 *   React Router v6 listens to popstate and re-renders with the new URL.
 *
 * Required env vars (see .env.local.example):
 *   PLAYWRIGHT_BASE_URL             — tenant subdomain URL
 *   PORTH_PLATFORM_BASE_URL         — platform admin UI URL (root subdomain)
 *   PORTH_API_URL                   — Porth API base URL (no trailing slash)
 *   PORTH_AUTH_TEST_TOKEN           — service token for direct API calls
 *   PORTH_PLATFORM_ADMIN_EMAIL / PORTH_PLATFORM_ADMIN_PASSWORD
 *   PORTH_TENANT_CONFIG             — JSON: {"domain":"...","client_id":"...","audience":"..."}
 *   PORTH_TENANT_USER_EMAIL / PORTH_TENANT_USER_PASSWORD   — controller user
 */
import { test, expect, Browser, Page, request as playwrightRequest } from '@playwright/test'

const PLATFORM_ADMIN_EMAIL = process.env.PORTH_PLATFORM_ADMIN_EMAIL ?? ''
const PLATFORM_ADMIN_PASSWORD = process.env.PORTH_PLATFORM_ADMIN_PASSWORD ?? ''
const TENANT_USER_EMAIL = process.env.PORTH_TENANT_USER_EMAIL ?? ''
const TENANT_USER_PASSWORD = process.env.PORTH_TENANT_USER_PASSWORD ?? ''
const PORTH_API_URL = (process.env.PORTH_API_URL ?? '').replace(/\/$/, '')
const PORTH_AUTH_TEST_TOKEN = process.env.PORTH_AUTH_TEST_TOKEN ?? ''

const TENANT_CONFIG: { domain?: string; client_id?: string; audience?: string } = (() => {
  const raw = process.env.PORTH_TENANT_CONFIG
  if (!raw) return {}

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

  const normalise = (obj: Record<string, unknown>) => {
    if (obj && typeof obj === 'object') {
      if (typeof obj.domain === 'string') return obj as { domain: string; client_id?: string; audience?: string }
      const auth0 = obj.auth0 as Record<string, unknown> | undefined
      if (auth0 && typeof auth0.domain === 'string') {
        console.log(`PORTH_TENANT_CONFIG: extracted from .auth0 subsection (domain=${auth0.domain})`)
        return auth0 as { domain: string; client_id?: string; audience?: string }
      }
    }
    return null
  }

  try { const r = normalise(JSON.parse(raw)); if (r) return r } catch {}
  try { const r = normalise(JSON.parse(raw.replace(/[\x00-\x1F\x7F]/g, ''))); if (r) return r } catch {}
  try { const r = normalise(JSON.parse(JSON.parse(raw))); if (r) return r } catch {}

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

const E2E_TENANT_ID = 'demo-tenant'

const PLATFORM_BASE_URL =
  process.env.PORTH_PLATFORM_BASE_URL ||
  (process.env.PLAYWRIGHT_BASE_URL ? (() => {
    try {
      const url = new URL(process.env.PLAYWRIGHT_BASE_URL!)
      const parts = url.hostname.split('.')
      if (parts.length > 3) {
        url.hostname = parts.slice(1).join('.')
        return url.origin
      }
    } catch { /* malformed URL — fall through */ }
    return process.env.PLAYWRIGHT_BASE_URL!
  })() : 'http://localhost:5173')

const TENANT_BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173'

const DEFAULT_MAPPING_SOURCE = {
  schema_version: '2.0' as const,
  fields: [
    {
      name: 'roles',
      source: 'https://porth.io/roles',
      type: 'collection' as const,
      required: false,
      ops: [{ op: 'resolve_roles' as const }],
    },
  ],
  default_roles: [] as string[],
}

async function signIn(page: Page, email: string, password: string) {
  if (!page.url().includes('auth0.com')) {
    const t0 = Date.now()
    console.log(`signIn: at ${page.url().replace(/[?#].*$/, '')}`)
    const signInButton = page.getByRole('button', { name: 'Sign in' })
    await signInButton.waitFor({ state: 'visible', timeout: 90000 })
    console.log(`signIn: Sign in button visible (${Date.now() - t0} ms)`)
    await signInButton.click()
    await page.waitForURL(/auth0\.com|eu\.auth0\.com/, { timeout: 90000 })
    console.log(`signIn: at auth0 (${Date.now() - t0} ms)`)
  }
  await page.getByLabel('Email address').fill(email)
  await page.locator('#password').fill(password)
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.waitForURL(url => !url.href.includes('auth0.com'), { timeout: 30000 })
  await page.waitForFunction(
    () => !window.location.search.includes('code='),
    { timeout: 20000 }
  ).catch(() => {})
}

/**
 * Ensure a role exists for the tenant with the given name and source_key.
 *
 * - If the role doesn't exist: create it (POST /roles/).
 * - If it already exists (409): list roles to find the existing record, then
 *   PATCH it to set source_key. This repairs roles that were previously
 *   created without source_key (which would make resolve_roles skip them).
 *
 * source_key MUST be set: the Porth resolve_roles op builds an in-memory
 * registry keyed by source_key. Roles without it are silently skipped.
 */
async function ensureRoleWithSourceKey(
  apiCtx: Awaited<ReturnType<typeof playwrightRequest.newContext>>,
  headers: Record<string, string>,
  tenantId: string,
  name: string,
  sourceKey: string,
  description: string,
): Promise<string | null> {
  const createResp = await apiCtx.post(`${PORTH_API_URL}/roles/`, {
    headers,
    data: { tenant_id: tenantId, name, source_key: sourceKey, description },
  })

  if (createResp.ok()) {
    const body = (await createResp.json()) as { id: string }
    console.log(`✅ Created role '${name}' with source_key='${sourceKey}'`)
    return body.id
  }

  if (createResp.status() !== 409) {
    console.warn(`Failed to create role '${name}': HTTP ${createResp.status()} — ${await createResp.text()}`)
    return null
  }

  // Role already exists — find its ID and PATCH source_key onto it.
  // Roles without source_key are invisible to resolve_roles, so this repair
  // step is essential for feature branches where the role was created in a
  // prior run before this fix was applied.
  console.log(`ℹ️ Role '${name}' already exists — patching source_key='${sourceKey}'`)
  const listResp = await apiCtx.get(`${PORTH_API_URL}/roles/?tenant_id=${tenantId}`, { headers })
  if (!listResp.ok()) {
    console.warn(`Failed to list roles: HTTP ${listResp.status()}`)
    return null
  }
  const roles = (await listResp.json()) as Array<{ id: string; name: string }>
  const existing = roles.find(r => r.name === name)
  if (!existing) {
    console.warn(`Role '${name}' not found in list after 409 — cannot patch source_key`)
    return null
  }
  const patchResp = await apiCtx.patch(`${PORTH_API_URL}/roles/${tenantId}/${existing.id}`, {
    headers,
    data: { source_key: sourceKey },
  })
  if (!patchResp.ok()) {
    console.warn(`Failed to PATCH source_key on role '${name}': HTTP ${patchResp.status()} — ${await patchResp.text()}`)
  } else {
    console.log(`✅ Patched source_key='${sourceKey}' on existing role '${name}'`)
  }
  return existing.id
}

// All sample-app permission keys — assigned in full to tenant-admin.
// Tenant-admin is the inverse of platform-admin: platform-admin manages
// cross-tenant infrastructure (orgs, tenants, settings); tenant-admin has
// full access to everything within their tenant.
const ALL_SAMPLE_APP_PERMISSION_KEYS = [
  'dashboard.read',
  'ar.invoices.read',
  'ar.invoices.write',
  'ap.bills.read',
  'ap.bills.write',
  'approvals.read',
  'approvals.write',
]

/**
 * Seed sample-app permissions + required roles with source_key set.
 *
 * Both tenant-admin and controller need source_key so resolve_roles can
 * match JWT claim values to Porth roles. Idempotent via 409 + PATCH repair.
 *
 * tenant-admin receives all sample-app permissions — it is the inverse of
 * platform-admin (who manages cross-tenant infrastructure, not app data).
 */
async function seedPermissionsAndRoles(tenantId: string) {
  if (!PORTH_API_URL || !PORTH_AUTH_TEST_TOKEN) {
    console.warn('Skipping seeding: PORTH_API_URL or PORTH_AUTH_TEST_TOKEN not set')
    return
  }

  const apiCtx = await playwrightRequest.newContext()
  const headers = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${PORTH_AUTH_TEST_TOKEN}`,
  }

  // Register sample-app permissions
  const permResp = await apiCtx.post(`${PORTH_API_URL}/permissions/`, {
    headers,
    data: {
      tenant_id: tenantId,
      app_namespace: 'sample-app',
      permissions: [
        { key: 'dashboard.read',    display_name: 'View Dashboard',       category: 'Dashboard',           app_namespace: 'sample-app', sort_order: 1  },
        { key: 'ar.invoices.read',  display_name: 'View Invoices',        category: 'Accounts Receivable', app_namespace: 'sample-app', sort_order: 10 },
        { key: 'ar.invoices.write', display_name: 'Create/Edit Invoices', category: 'Accounts Receivable', app_namespace: 'sample-app', sort_order: 11 },
        { key: 'ap.bills.read',     display_name: 'View Bills',           category: 'Accounts Payable',    app_namespace: 'sample-app', sort_order: 20 },
        { key: 'ap.bills.write',    display_name: 'Create/Edit Bills',    category: 'Accounts Payable',    app_namespace: 'sample-app', sort_order: 21 },
        { key: 'approvals.read',    display_name: 'View Approval Queue',  category: 'Approvals',           app_namespace: 'sample-app', sort_order: 30 },
        { key: 'approvals.write',   display_name: 'Approve/Reject',       category: 'Approvals',           app_namespace: 'sample-app', sort_order: 31 },
      ],
    },
  })
  if (!permResp.ok()) {
    console.warn(`Failed to batch-register permissions: HTTP ${permResp.status()} — ${await permResp.text()}`)
  }

  // Seed tenant-admin role with source_key (required for claim mapping to resolve it)
  const tenantAdminRoleId = await ensureRoleWithSourceKey(
    apiCtx, headers, tenantId,
    'tenant-admin', 'tenant-admin',
    'Tenant Administrator — manages roles and claim mapping',
  )

  // Assign all sample-app permissions to tenant-admin. Tenant-admin is the
  // inverse of platform-admin: full access to all tenant-level app data.
  if (tenantAdminRoleId) {
    const assignResp = await apiCtx.put(
      `${PORTH_API_URL}/roles/${tenantId}/${tenantAdminRoleId}/permissions`,
      { headers, data: ALL_SAMPLE_APP_PERMISSION_KEYS },
    )
    if (!assignResp.ok()) {
      console.warn(`Failed to assign permissions to tenant-admin: HTTP ${assignResp.status()} — ${await assignResp.text()}`)
    } else {
      console.log(`✅ All sample-app permissions assigned to tenant-admin role`)
    }
  }

  // Seed controller role with source_key. The Roles UI (test 2) will try to
  // create it again — it'll get a 409 and click Cancel, which is fine.
  // Seeding via API here ensures source_key is always set, even if the UI
  // creates the role without it on the first run.
  await ensureRoleWithSourceKey(
    apiCtx, headers, tenantId,
    'controller', 'controller',
    'Controller — full access to AR/AP and approvals',
  )

  await apiCtx.dispose()
  console.log(`✅ Permissions and roles seeded for ${tenantId}`)
}

async function patchIdpConfig(tenantId: string) {
  if (!TENANT_CONFIG.domain || !PORTH_API_URL || !PORTH_AUTH_TEST_TOKEN) {
    console.warn('Skipping IdP config patch: TENANT_CONFIG, PORTH_API_URL or PORTH_AUTH_TEST_TOKEN not set')
    return
  }
  const apiCtx = await playwrightRequest.newContext()
  try {
    const resp = await apiCtx.patch(`${PORTH_API_URL}/tenants/${tenantId}`, {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${PORTH_AUTH_TEST_TOKEN}`,
      },
      data: {
        idp_config_override: {
          domain: TENANT_CONFIG.domain,
          client_id: TENANT_CONFIG.client_id,
          audience: TENANT_CONFIG.audience,
        },
      },
    })
    if (!resp.ok()) {
      console.warn(`Failed to patch IdP config: HTTP ${resp.status()} — ${await resp.text()}`)
    } else {
      console.log(`✅ IdP config patched for ${tenantId}`)
    }
  } finally {
    await apiCtx.dispose()
  }
}

async function saveClaimMappingConfig(tenantId: string) {
  if (!PORTH_API_URL || !PORTH_AUTH_TEST_TOKEN) {
    console.warn('Skipping claim mapping config save: PORTH_API_URL or PORTH_AUTH_TEST_TOKEN not set')
    return
  }
  const apiCtx = await playwrightRequest.newContext()
  try {
    const resp = await apiCtx.post(
      `${PORTH_API_URL}/claim-mapping-configs/?tenant_id=${encodeURIComponent(tenantId)}`,
      {
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${PORTH_AUTH_TEST_TOKEN}`,
        },
        data: { mapping_source: DEFAULT_MAPPING_SOURCE },
      },
    )
    if (!resp.ok()) {
      console.warn(
        `Failed to save claim mapping config: HTTP ${resp.status()} — ${await resp.text()}`,
      )
    } else {
      console.log(`✅ Claim mapping config saved for ${tenantId}`)
    }
  } finally {
    await apiCtx.dispose()
  }
}

async function setupE2ETenant(browser: Browser) {
  if (!PLATFORM_ADMIN_EMAIL || !TENANT_CONFIG.domain) {
    console.warn('Skipping e2e tenant setup: PORTH_PLATFORM_ADMIN_EMAIL or PORTH_TENANT_CONFIG not set')
    return
  }

  const page = await browser.newPage()
  try {
    // ── 1. Sign in as platform admin ────────────────────────────────────────
    await page.goto(PLATFORM_BASE_URL)
    await signIn(page, PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_PASSWORD)
    await page.waitForURL('**/admin/platform/organizations**', { timeout: 120000 })
    await page.getByRole('heading', { name: 'Organizations' }).waitFor({ state: 'visible', timeout: 30000 })

    // ── 2. Create org + first tenant (409 = already exists) ──────────────────
    await page.getByRole('button', { name: '+ New Organization' }).click()
    await page.getByRole('heading', { name: 'New Organization' }).waitFor({ state: 'visible' })
    const modalForm = page.locator('form').last()
    await modalForm.locator('input[type="text"]').nth(0).fill('Demo Corp')
    await modalForm.locator('input[type="text"]').nth(1).fill('demo-tenant')
    await modalForm.locator('input[type="text"]').nth(2).fill('Demo Tenant Dev')
    await page.getByRole('button', { name: 'Create' }).click()
    await page.waitForTimeout(2000)
    const orgModalVisible = await page.getByRole('heading', { name: 'New Organization' }).isVisible()
    if (orgModalVisible) {
      console.log('ℹ️ New Organization modal still open (409 conflict) — will be dismissed by navigation')
    }

    // ── 3. Seed permissions + roles with source_key ───────────────────────
    await seedPermissionsAndRoles(E2E_TENANT_ID)

    // ── 4. Patch IdP config via API ──────────────────────────────────────────
    await patchIdpConfig(E2E_TENANT_ID)

    // ── 5. Save default claim mapping config via API ──────────────────────────
    await saveClaimMappingConfig(E2E_TENANT_ID)

    console.log(`✅ E2E tenant setup complete for ${E2E_TENANT_ID}`)
  } finally {
    await page.close()
  }
}

test.describe.serial('Acceptance', () => {
  test.setTimeout(240000)

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(300000)
    await setupE2ETenant(browser)
  })

  test('platform admin sees organizations list and Demo Corp is present', async ({ page }) => {
    await page.goto(PLATFORM_BASE_URL)
    await signIn(page, PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_PASSWORD)
    await page.waitForURL('**/admin/platform/organizations**', { timeout: 120000 })
    await expect(page.getByRole('heading', { name: 'Organizations' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('cell', { name: 'Demo Corp' }).first()).toBeVisible({ timeout: 10000 })
  })

  test('platform admin assigns permissions to controller role via Roles UI', async ({ page }) => {
    await page.goto(PLATFORM_BASE_URL)
    await signIn(page, PLATFORM_ADMIN_EMAIL, PLATFORM_ADMIN_PASSWORD)
    await page.waitForURL('**/admin/platform/organizations**', { timeout: 120000 })
    await page.getByRole('heading', { name: 'Organizations' }).waitFor({ state: 'visible', timeout: 30000 })

    await page.evaluate((tenantId) => {
      window.history.pushState({}, '', `/admin/tenant/roles?tenantId=${tenantId}`)
      window.dispatchEvent(new PopStateEvent('popstate'))
    }, E2E_TENANT_ID)
    await expect(page.getByRole('heading', { name: 'Roles' })).toBeVisible({ timeout: 30000 })

    // The controller role was seeded via API in beforeAll with source_key set.
    // Try to create via UI anyway (idempotent — 409 handled via Cancel button).
    await page.getByRole('button', { name: '+ New Role' }).click()
    await page.getByRole('heading', { name: 'New Role' }).waitFor({ state: 'visible' })
    const roleModalForm = page.locator('form').last()
    await roleModalForm.locator('input[type="text"]').nth(0).fill('controller')
    await roleModalForm.locator('input[type="text"]').nth(1).fill('Controller — full access to AR/AP and approvals')
    await page.getByRole('button', { name: 'Create' }).click()
    const roleModalClosed = await page.getByRole('heading', { name: 'New Role' })
      .waitFor({ state: 'hidden', timeout: 10000 })
      .then(() => true)
      .catch(() => false)
    if (!roleModalClosed) {
      console.log('ℹ️ New Role modal still open — role already exists (seeded via API), clicking Cancel')
      await page.getByRole('button', { name: 'Cancel' }).click()
      await page.getByRole('heading', { name: 'New Role' })
        .waitFor({ state: 'hidden', timeout: 5000 })
        .catch(() => {})
    }

    // Open side panel and assign permissions
    const controllerRow = page.getByRole('row').filter({ hasText: 'controller' }).first()
    await expect(controllerRow).toBeVisible({ timeout: 10000 })
    await controllerRow.click()
    await page.locator('label').filter({ hasText: 'View Dashboard' }).waitFor({ state: 'visible', timeout: 15000 })

    const controllerPerms = [
      'View Dashboard',
      'View Invoices',
      'Create/Edit Invoices',
      'View Approval Queue',
      'Approve/Reject',
    ]
    for (const permName of controllerPerms) {
      const checkbox = page.locator('label').filter({ hasText: permName }).locator('input[type="checkbox"]')
      if (!(await checkbox.isChecked())) {
        await checkbox.check()
      }
    }

    const saveBtn = page.getByRole('button', { name: 'Save Permissions' })
    if (await saveBtn.isEnabled()) {
      await saveBtn.click()
      await page.waitForTimeout(1500)
      await expect(page.locator('.bg-red-50').first()).not.toBeVisible()
    } else {
      console.log('ℹ️ Save Permissions button is disabled — permissions already current')
    }

    console.log('✅ Controller role verified and permissions confirmed via Roles UI')
  })

  test('controller can navigate to AR page', async ({ page }) => {
    test.skip(!TENANT_USER_EMAIL, 'PORTH_TENANT_USER_EMAIL not configured')
    test.skip(!TENANT_CONFIG.domain, 'PORTH_TENANT_CONFIG not configured — tenant has no IdP')

    await page.goto(TENANT_BASE_URL)
    await signIn(page, TENANT_USER_EMAIL, TENANT_USER_PASSWORD)

    // Wait for the AR sidebar link — appears only after /users/me resolves the
    // controller role via claim mapping. 120s covers Lambda cold-start latency.
    const arLink = page.getByRole('link', { name: /Accounts Receivable/i })
    const roleResolved = await arLink
      .waitFor({ state: 'visible', timeout: 120000 })
      .then(() => true)
      .catch(() => false)

    if (roleResolved) {
      await arLink.click()
      await expect(page.getByRole('heading', { name: 'Accounts Receivable' })).toBeVisible({ timeout: 10000 })
      await expect(page).toHaveURL(/\/ar/)
      console.log('✅ Controller can see and navigate to AR page')
    } else {
      // AR link didn't appear in 120s — navigate via pushState (never page.goto)
      console.log('ℹ️ AR link not visible after 120 s — navigating via pushState to /ar')
      await page.evaluate(() => {
        window.history.pushState({}, '', '/ar')
        window.dispatchEvent(new PopStateEvent('popstate'))
      })
      const arHeading = page.getByRole('heading', { name: 'Accounts Receivable' })
      const outcome = await Promise.race([
        arHeading.waitFor({ state: 'visible', timeout: 30000 }).then(() => 'ar' as const),
        page.waitForURL(/unauthorized/, { timeout: 30000 }).then(() => 'unauthorized' as const),
      ]).catch(() => 'unknown' as const)

      if (outcome === 'ar') {
        await expect(page).toHaveURL(/\/ar/)
        console.log('✅ Controller can access AR page (role resolved, navigated via pushState)')
      } else if (outcome === 'unauthorized') {
        // AR link not visible AND /unauthorized — role did not resolve.
        // This is a REAL failure: the controller user cannot access AR.
        throw new Error(
          'Controller user was redirected to /unauthorized — the controller Porth role ' +
          'did not resolve from the JWT claim. Check that: (1) the Auth0 user has the ' +
          '"controller" Auth0 role assigned, (2) the Auth0 post-login Action injects ' +
          'roles into the https://porth.io/roles JWT claim, and (3) the Porth controller ' +
          'role has source_key="controller" (seeded in beforeAll — check API logs).'
        )
      } else {
        await expect(arHeading).toBeVisible({ timeout: 1000 })
      }
    }
  })
})
