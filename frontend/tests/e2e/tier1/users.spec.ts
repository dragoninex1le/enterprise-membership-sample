import { test, expect } from '@playwright/test'
import {
  mockBootstrap,
  mockTenants,
  mockUsers,
  mockRoles,
  mockRolePermissions,
  DEFAULT_ACTIVE_USER,
  DEFAULT_SUSPENDED_USER,
  DEFAULT_TENANT,
} from '../helpers/mocks'

// The page also needs user-level role endpoints when side panel opens
async function mockUserRoles(page: import('@playwright/test').Page) {
  await page.route(/\/users\/[^/]+\/roles($|\?)/, (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
}

test.describe('Users page', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
    await mockTenants(page)
    await mockUsers(page)
    await mockRoles(page)
    await mockRolePermissions(page)
    await mockUserRoles(page)
  })

  test('renders Users heading', async ({ page }) => {
    await page.goto('/admin/tenant/users?tenantId=test-tenant')
    await expect(page.getByRole('heading', { name: 'Users' })).toBeVisible()
  })

  test('page is accessible as platform-admin', async ({ page }) => {
    await page.goto('/admin/tenant/users?tenantId=test-tenant')
    await expect(page).not.toHaveURL(/unauthorized/)
  })

  test('renders tenant selector', async ({ page }) => {
    await page.goto('/admin/tenant/users?tenantId=test-tenant')
    await expect(page.getByRole('combobox')).toBeVisible()
  })

  test('renders user table with both users', async ({ page }) => {
    await page.goto('/admin/tenant/users?tenantId=test-tenant')
    await expect(page.getByText(DEFAULT_ACTIVE_USER.display_name!)).toBeVisible()
    await expect(page.getByText(DEFAULT_SUSPENDED_USER.display_name!)).toBeVisible()
  })

  test('active user shows active status badge', async ({ page }) => {
    await page.goto('/admin/tenant/users?tenantId=test-tenant')
    // active badge from StatusBadge component
    await expect(page.getByText('active').first()).toBeVisible()
  })

  test('clicking user row opens side panel with email and suspend button', async ({ page }) => {
    await page.goto('/admin/tenant/users?tenantId=test-tenant')
    await page.getByText(DEFAULT_ACTIVE_USER.display_name!).first().click()
    // Side panel shows the Suspend User button
    await expect(page.getByRole('button', { name: 'Suspend User' })).toBeVisible()
    // Side panel shows email (may appear in table too -- use first match)
    await expect(page.getByText(DEFAULT_ACTIVE_USER.email).first()).toBeVisible()
  })

  test('clicking suspended user shows Reactivate button', async ({ page }) => {
    await page.goto('/admin/tenant/users?tenantId=test-tenant')
    await page.getByText(DEFAULT_SUSPENDED_USER.display_name!).click()
    await expect(page.getByRole('button', { name: 'Reactivate User' })).toBeVisible()
  })

  test('Save Roles button is present in the side panel', async ({ page }) => {
    await page.goto('/admin/tenant/users?tenantId=test-tenant')
    await page.getByText(DEFAULT_ACTIVE_USER.display_name!).click()
    await expect(page.getByRole('button', { name: 'Save Roles' })).toBeVisible()
  })

  test('tenant selector shows the mocked tenants', async ({ page }) => {
    await page.goto('/admin/tenant/users?tenantId=test-tenant')
    await expect(page.getByRole('option', { name: new RegExp(DEFAULT_TENANT.display_name) })).toBeAttached()
  })
})
