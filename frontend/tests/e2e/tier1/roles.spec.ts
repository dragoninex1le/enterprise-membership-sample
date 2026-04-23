import { test, expect } from '@playwright/test'
import {
  mockBootstrap,
  mockRoles,
  mockPermissions,
  mockRolePermissions,
  DEFAULT_SYSTEM_ROLE,
  DEFAULT_CUSTOM_ROLE,
} from '../helpers/mocks'

test.describe('Roles page', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
    await mockRoles(page)
    await mockPermissions(page)
    await mockRolePermissions(page)
  })

  test('renders roles table with both roles', async ({ page }) => {
    await page.goto('/admin/tenant/roles?tenantId=test-tenant')
    await expect(page.getByRole('heading', { name: 'Roles' })).toBeVisible()
    await expect(page.getByText(DEFAULT_SYSTEM_ROLE.name)).toBeVisible()
    await expect(page.getByText(DEFAULT_CUSTOM_ROLE.name)).toBeVisible()
  })

  test('system role shows system badge', async ({ page }) => {
    await page.goto('/admin/tenant/roles?tenantId=test-tenant')
    // The system role row has a "system" badge
    await expect(page.getByText('system').first()).toBeVisible()
  })

  test('clicking custom role opens side panel with permissions checklist', async ({ page }) => {
    await page.goto('/admin/tenant/roles?tenantId=test-tenant')
    // Click the custom role row
    await page.getByText(DEFAULT_CUSTOM_ROLE.name).click()
    // Side panel heading
    await expect(page.getByRole('heading', { name: DEFAULT_CUSTOM_ROLE.name })).toBeVisible()
    // Delete Role button should be present for non-system roles
    await expect(page.getByRole('button', { name: 'Delete Role' })).toBeVisible()
    // Save Permissions button should be present
    await expect(page.getByRole('button', { name: 'Save Permissions' })).toBeVisible()
  })

  test('clicking system role does NOT show Delete button', async ({ page }) => {
    await page.goto('/admin/tenant/roles?tenantId=test-tenant')
    await page.getByText(DEFAULT_SYSTEM_ROLE.name).click()
    // Panel should open
    await expect(page.getByRole('heading', { name: DEFAULT_SYSTEM_ROLE.name })).toBeVisible()
    // Delete button must NOT appear for system roles
    await expect(page.getByRole('button', { name: 'Delete Role' })).not.toBeVisible()
  })

  test('New Role button is visible', async ({ page }) => {
    await page.goto('/admin/tenant/roles?tenantId=test-tenant')
    await expect(page.getByRole('button', { name: '+ New Role' })).toBeVisible()
  })
})
