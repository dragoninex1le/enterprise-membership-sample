import { test, expect } from '@playwright/test'
import {
  mockBootstrap,
  mockOrgs,
  mockTenants,
  DEFAULT_ORG,
  DEFAULT_ORG_2,
  DEFAULT_TENANT,
} from '../helpers/mocks'

test.describe('Organizations page', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
    await mockOrgs(page)
    await mockTenants(page)
  })

  test('renders tenant list with org names in filter', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    await expect(page.getByRole('heading', { name: 'Tenants' })).toBeVisible()
    // org names appear as <option> values in the filter <select> — check via toContainText
    const orgFilter = page.locator('select').first()
    await expect(orgFilter).toContainText(DEFAULT_ORG.name)
    await expect(orgFilter).toContainText(DEFAULT_ORG_2.name)
  })

  test('New Organization button is visible', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    await expect(page.getByRole('button', { name: '+ New Organization' })).toBeVisible()
  })

  test('clicking Manage on a tenant row navigates to claim-config page', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    // mock returns same tenants for both orgs, so rows are duplicated — use .first()
    await expect(page.getByRole('cell', { name: DEFAULT_TENANT.display_name }).first()).toBeVisible()
    await page.getByRole('button', { name: 'Manage \u2192' }).first().click()
    await expect(page).toHaveURL(new RegExp(`/admin/tenant/claim-config\\?tenantId=${DEFAULT_TENANT.tenant_id}`))
  })
})
