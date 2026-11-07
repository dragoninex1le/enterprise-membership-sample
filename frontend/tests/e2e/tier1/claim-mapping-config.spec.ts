// A tenant's claim mapping -- PORTH-131, with the token tester (PORTH-132) folded in.
// A platform admin reaches it from the tenant's page; it is never about no tenant in particular.
import { test, expect } from '@playwright/test'
import {
  DEFAULT_TENANT,
  mockBootstrap,
  mockClaimConfig,
  mockClaimConfigVersions,
} from '../helpers/mocks'

const PAGE = '/admin/platform/tenants/test-tenant/claim-mapping'

test.describe('Claim mapping, on a tenant page', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
    await mockClaimConfig(page)
    await mockClaimConfigVersions(page)
  })

  test('names the tenant it belongs to', async ({ page }) => {
    await page.goto(PAGE)
    await expect(page.getByRole('heading', { name: DEFAULT_TENANT.display_name })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Claim mapping' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Claim mapping', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: '← All tenants' })).toBeVisible()
  })

  test('the editor holds the mapping from the API', async ({ page }) => {
    await page.goto(PAGE)
    await expect(page.locator('textarea').first()).toHaveValue(/resolve_roles/)
  })

  test('version history shows both versions, each with a rollback', async ({ page }) => {
    await page.goto(PAGE)
    await expect(page.getByRole('heading', { name: 'Version History' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Rollback' })).toHaveCount(2)
  })

  test('Save and Compile Preview are offered', async ({ page }) => {
    await page.goto(PAGE)
    await expect(page.getByRole('button', { name: 'Save' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Compile Preview' })).toBeVisible()
  })

  test('a token tested against the mapping shows the roles it resolves to', async ({ page }) => {
    await page.goto(PAGE)
    await expect(page.locator('textarea').first()).toHaveValue(/resolve_roles/)
    await expect(page.getByRole('heading', { name: 'Test a token' })).toBeVisible()
    await page.getByPlaceholder('Paste decoded JWT claims as JSON').fill('{"https://porth.io/roles": ["controller"]}')
    await page.getByRole('button', { name: 'Evaluate' }).click()
    await expect(page.getByText('Matched roles:', { exact: true })).toBeVisible()
    await expect(page.getByText('controller', { exact: true })).toBeVisible()
  })

  test('the sidebar names the tenant being managed', async ({ page }) => {
    await page.goto(PAGE)
    await expect(page.getByText('Managing Tenant')).toBeVisible()
    await expect(page.getByRole('navigation').first().getByText('test-tenant', { exact: true })).toBeVisible()
  })
})

test.describe('The platform tenant\'s claim mapping', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
    await mockClaimConfig(page)
    await mockClaimConfigVersions(page)
    await page.route(/\/tenants\/platform($|\?)/, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ...DEFAULT_TENANT, tenant_id: 'platform', display_name: 'Platform' }) }))
  })

  test('is shown read-only: the install owns it', async ({ page }) => {
    await page.goto('/admin/platform/tenants/platform/claim-mapping')
    await expect(page.getByText('written by the Porth install')).toBeVisible()
    await expect(page.locator('textarea').first()).toHaveAttribute('readonly', '')
    await expect(page.getByRole('button', { name: 'Save' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Rollback' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Evaluate' })).toBeVisible()
  })
})

test.describe('The old claim mapping addresses', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
    await mockClaimConfig(page)
    await mockClaimConfigVersions(page)
  })

  test('with a tenant, a platform admin is taken to that tenant\'s page', async ({ page }) => {
    await page.goto('/admin/tenant/claim-config?tenantId=test-tenant')
    await expect(page).toHaveURL(/\/admin\/platform\/tenants\/test-tenant\/claim-mapping$/)
    await expect(page.getByRole('heading', { name: 'Claim mapping' })).toBeVisible()
  })

  test('the old token tester address lands on the claim mapping', async ({ page }) => {
    await page.goto('/admin/tenant/claim-mappings?tenantId=test-tenant')
    await expect(page).toHaveURL(/\/admin\/platform\/tenants\/test-tenant\/claim-mapping$/)
  })

  test('with no tenant, a platform admin is sent to choose one', async ({ page }) => {
    await page.goto('/admin/tenant/claim-config')
    await expect(page).toHaveURL(/\/admin\/platform\/tenants$/)
  })
})
