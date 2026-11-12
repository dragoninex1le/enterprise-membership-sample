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

  test('New Tenant walks through organization, tenant, identity provider and roles', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    await expect(page.getByRole('button', { name: '+ New Organization' })).toHaveCount(0)
    await page.getByRole('button', { name: '+ New Tenant' }).click()

    await expect(page.getByLabel('Organization Name', { exact: true })).toHaveCount(0)
    await page.getByLabel('Organization', { exact: true }).selectOption({ label: '+ New organization…' })
    await page.getByLabel('Organization Name', { exact: true }).fill('Acme')
    await page.getByLabel('Slug', { exact: true }).fill('acme')
    await page.getByRole('button', { name: 'Next' }).click()

    await page.getByLabel('Tenant ID', { exact: true }).fill('acme-prod')
    await page.getByLabel('Display Name', { exact: true }).fill('Acme')
    await page.getByRole('button', { name: 'Next' }).click()

    await expect(page.getByRole('checkbox', { name: 'Identity Provider' })).toHaveCount(0)
    const provider = page.getByLabel('Identity Provider', { exact: true })
    await expect(provider.locator('option')).toHaveText(['Auth0', 'Keycloak'])
    await provider.selectOption({ label: 'Keycloak' })
    await expect(page.getByLabel('Realm', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Auth0 Organization ID', { exact: true })).toHaveCount(0)
    await page.getByLabel('Server URL', { exact: true }).fill('https://keycloak.example.com')
    await page.getByLabel('Realm', { exact: true }).fill('acme')
    await page.getByLabel('Client ID', { exact: true }).fill('acme-client')
    // PORTH-669: a Keycloak tenant names its Keycloak organization by alias.
    await page.getByLabel('Organization alias', { exact: true }).fill('ems-keycloak')
    await page.getByRole('button', { name: 'Next' }).click()

    await expect(page.getByLabel('Roles Claim', { exact: true })).toHaveValue('realm_access.roles')
    await expect(page.getByLabel('Admin Role Value', { exact: true })).toHaveValue('tenant-admin')
    await expect(page.getByRole('button', { name: 'Create' })).toBeVisible()
  })

  test('clicking Manage on a tenant row opens that tenant\'s page', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    // mock returns same tenants for both orgs, so rows are duplicated — use .first()
    await expect(page.getByRole('cell', { name: DEFAULT_TENANT.display_name }).first()).toBeVisible()
    await page.getByRole('button', { name: 'Manage \u2192' }).first().click()
    await expect(page).toHaveURL(new RegExp(`/admin/platform/tenants/${DEFAULT_TENANT.tenant_id}/roles$`))
  })
})
