// Role name constants — these must match what the Porth bootstrap creates and
// what the IdP Action injects into the JWT via the claim mapping.
// Centralised here to avoid duplication across router, sidebar, and hooks.

/** The Porth platform-level role assigned to Estyn operators. */
export const PLATFORM_ADMIN = 'platform-admin'

export const PERMISSIONS = {
  DASHBOARD_READ: 'dashboard.read',
  AR_INVOICES_READ: 'ar.invoices.read',
  AR_INVOICES_WRITE: 'ar.invoices.write',
  AP_BILLS_READ: 'ap.bills.read',
  AP_BILLS_WRITE: 'ap.bills.write',
  APPROVALS_READ: 'approvals.read',
  APPROVALS_WRITE: 'approvals.write',
} as const

export const SAMPLE_ROLES = {
  VIEWER: 'viewer',
  AR_CLERK: 'ar-clerk',
  AP_CLERK: 'ap-clerk',
  CONTROLLER: 'controller',
  TENANT_ADMIN: 'tenant-admin',
} as const
