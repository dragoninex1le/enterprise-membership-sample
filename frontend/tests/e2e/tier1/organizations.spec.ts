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

  test('a new organization is created through New Tenant, along with its first tenant', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    await expect(page.getByRole('button', { name: '+ New Organization' })).toHaveCount(0)
    await page.getByRole('button', { name: '+ New Tenant' }).click()
    await expect(page.getByLabel('Organization Name', { exact: true })).toHaveCount(0)
    await page.getByLabel('Organization', { exact: true }).selectOption({ label: '+ New organization…' })
    await expect(page.getByLabel('Organization Name', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Slug', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Tenant ID', { exact: true })).toBeVisible()
  })

  test('every tenant has an identity provider, and the provider decides its fields', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    await page.getByRole('button', { name: '+ New Tenant' }).click()
    await expect(page.getByRole('checkbox', { name: 'Identity Provider' })).toHaveCount(0)
    const provider = page.getByLabel('Identity Provider', { exact: true })
    await expect(provider.locator('option')).toHaveText(['Auth0', 'Keycloak'])
    await expect(page.getByLabel('Domain', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Auth0 Organization ID', { exact: true })).toBeVisible()
    await provider.selectOption({ label: 'Keycloak' })
    await expect(page.getByLabel('Server URL', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Realm', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Auth0 Organization ID', { exact: true })).toHaveCount(0)
  })

  test('clicking Manage on a tenant row navigates to claim-config page', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    // mock returns same tenants for both orgs, so rows are duplicated — use .first()
    await expect(page.getByRole('cell', { name: DEFAULT_TENANT.display_name }).first()).toBeVisible()
    await page.getByRole('button', { name: 'Manage \u2192' }).first().click()
    await expect(page).toHaveURL(new RegExp(`/admin/tenant/claim-config\\?tenantId=${DEFAULT_TENANT.tenant_id}`))
  })
})
