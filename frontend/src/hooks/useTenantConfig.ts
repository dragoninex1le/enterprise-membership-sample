// Roles-claim namespace, for DISPLAY ONLY (the diagnostics panel on /unauthorized).
// Role resolution happens server-side in the authorizer against the claim-mapping
// config — nothing here affects it.
//
// The namespace is "{audience}/roles": Auth0's post-login Action namespaces custom
// claims with the API identifier, so the value is per-install and cannot be a
// shared constant. VITE_ROLES_NAMESPACE overrides it; the fallback is THIS
// install's audience-derived value. The old hardcoded https://porth.io/roles
// showed on an install whose real namespace is
// https://porth.ems.estynsoftware.io/roles, which is actively misleading when
// the thing you are debugging IS the namespace.
const ROLES_NAMESPACE =
  import.meta.env.VITE_ROLES_NAMESPACE ?? 'https://porth.ems.estynsoftware.io/roles'

export interface TenantConfig {
  tenantId: string
  /** Roles-claim namespace — used for display/diagnostics only. */
  rolesNamespace: string
}

function getTenantIdFromSubdomain(): string | null {
  const hostname = window.location.hostname
  // localhost / 127.0.0.1 — fall back to env var for dev
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return import.meta.env.VITE_DEV_TENANT_ID ?? null
  }
  // {tenant-id}.example.com → tenant-id
  const parts = hostname.split('.')
  if (parts.length < 3) return null

  const subdomain = parts[0]

  // Root admin URL rather than a customer tenant subdomain → platform tenant.
  const platformApex = import.meta.env.VITE_PLATFORM_APEX
  if (platformApex && subdomain === platformApex) {
    return 'platform'
  }

  return subdomain
}

/**
 * PORTH-531 (cookie/BFF mode): the tenant is the subdomain. That is the design —
 * the hostname IS the tenant identity, so nothing needs fetching to know it.
 *
 * There is no pre-login API call. Under the BFF the SPA holds no IdP
 * configuration (the proxy owns the upstream IdP entirely), and everything else
 * — org, roles, permissions — arrives authenticated from /auth/me and
 * /users/me after login.
 *
 * A pre-login fetch could not work here anyway: tenant records are written
 * env-scoped (ENV#{slot}#TENANT#…, ADR-Z8) and the public GET /tenants/{id}
 * route resolves env from the authorizer context, which is empty before login —
 * so it 404s on every record, platform included.
 */
export function useTenantConfig(): {
  config: TenantConfig | null
  loading: boolean
  error: string | null
} {
  const tenantId = getTenantIdFromSubdomain()

  if (!tenantId) {
    return {
      config: null,
      loading: false,
      error: 'Cannot determine tenant from hostname. Set VITE_DEV_TENANT_ID for local development.',
    }
  }

  return {
    config: { tenantId, rolesNamespace: ROLES_NAMESPACE },
    loading: false,
    error: null,
  }
}
