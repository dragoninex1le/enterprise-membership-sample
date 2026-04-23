import { test, expect } from '@playwright/test'
import {
  mockBootstrap,
  mockPermissions,
  DEFAULT_PERMISSIONS,
} from '../helpers/mocks'

test.describe('Permissions page', () => {
  test.beforeEach(async ({ page }) => {
    await mockBootstrap(page)
    await mockPermissions(page)
  })

  test('renders permissions heading', async ({ page }) => {
    await page.goto('/admin/tenant/permissions?tenantId=test-tenant')
    await expect(page.getByRole('heading', { name: 'Permissions' })).toBeVisible()
  })

  test('renders grouped category headers', async ({ page }) => {
    await page.goto('/admin/tenant/permissions?tenantId=test-tenant')
    // Categories from DEFAULT_PERMISSIONS: Accounts Receivable, Accounts Payable, Approvals
    await expect(page.getByText('Accounts Receivable', { exact: false }).first()).toBeVisible()
    await expect(page.getByText('Accounts Payable', { exact: false }).first()).toBeVisible()
    await expect(page.getByText('Approvals', { exact: false }).first()).toBeVisible()
  })

  test('renders permission display names', async ({ page }) => {
    await page.goto('/admin/tenant/permissions?tenantId=test-tenant')
    for (const perm of DEFAULT_PERMISSIONS) {
      await expect(page.getByText(perm.display_name)).toBeVisible()
    }
  })

  test('no create/edit/delete buttons present (read-only screen)', async ({ page }) => {
    await page.goto('/admin/tenant/permissions?tenantId=test-tenant')
    await expect(page.getByRole('button', { name: /new|create|edit|delete/i })).not.toBeVisible()
  })
})
