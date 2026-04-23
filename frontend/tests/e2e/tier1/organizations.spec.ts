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
    await expect(page.getByRole('option', { name: DEFAULT_ORG.name })).toBeVisible()
    await expect(page.getByRole('option', { name: DEFAULT_ORG_2.name })).toBeVisible()
  })

  test('New Organization button is visible', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    await expect(page.getByRole('button', { name: '+ New Organization' })).toBeVisible()
  })

  test('clicking Manage on a tenant row navigates to users page', async ({ page }) => {
    await page.goto('/admin/platform/tenants')
    await expect(page.getByText(DEFAULT_TENANT.display_name)).toBeVisible()
    await page.getByRole('button', { name: 'Manage \u2192' }).first().click()
    await expect(page).toHaveURL(new RegExp(`/admin/tenant/users\\?tenantId=${DEFAULT_TENANT.tenant_id}`))
  })
})
