import { useState, useEffect } from 'react'

// Default claim namespace used by the Porth platform IdP hook. Can be overridden
// per-tenant via idp_config_override.custom_claims.roles_namespace.
const DEFAULT_ROLES_NAMESPACE = 'https://porth.io/roles'

export interface TenantConfig {
  tenantId: string
  organizationId: string
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

  // If the subdomain matches the platform apex (i.e. we're at the root admin
  // URL rather than a customer tenant subdomain), use the platform tenant.
  const platformApex = import.meta.env.VITE_PLATFORM_APEX
  if (platformApex && subdomain === platformApex) {
    return 'platform'
  }

  return subdomain
}

/**
 * PORTH-531 (cookie/BFF mode): resolves the tenant identity from the hostname and
 * fetches the shared context from the Porth API at startup (this route is
 * unauthenticated — it runs before login).
 *
 * The SPA no longer configures an IdP client itself — the Porth BFF owns the
 * upstream IdP entirely — so this carries NO domain / client_id / audience. That
 * is the defining requirement of ADR-Z9: no vendor IdP configuration, and no
 * vendor SDK, in the browser.
 */
export function useTenantConfig(): {
  config: TenantConfig | null
  loading: boolean
  error: string | null
} {
  const [config, setConfig] = useState<TenantConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const tenantId = getTenantIdFromSubdomain()

    if (!tenantId) {
      setError('Cannot determine tenant from hostname. Set VITE_DEV_TENANT_ID for local development.')
      setLoading(false)
      return
    }

    const apiBase = import.meta.env.VITE_API_BASE_URL
    if (!apiBase) {
      setError('VITE_API_BASE_URL is not configured.')
      setLoading(false)
      return
    }

    // PORTH-514: the pre-login fetch ALWAYS targets the env-agnostic 'platform'
    // record, never the real tenant. The public GET /tenants/{id} route resolves
    // its environment from the authorizer context, which is empty before login —
    // so it sees env-agnostic records but 404s on the env-scoped ones
    // (ENV#{slot}#TENANT#…) every real tenant is written under. Requesting the
    // tenant here would fail on any env-scoped install, EMS included.
    fetch(`${apiBase}/tenants/platform`)
      .then(res => {
        if (!res.ok) throw new Error(`Platform config lookup failed: ${res.status}`)
        return res.json()
      })
      .then(tenant => {
        // Namespace only — not IdP configuration. Kept so the diagnostics panel
        // can show which claim the role mapping reads.
        const rolesNamespace =
          tenant.idp_config_override?.custom_claims?.roles_namespace ?? DEFAULT_ROLES_NAMESPACE

        setConfig({
          tenantId,
          // Porth Tenant model uses org_id (not organization_id)
          organizationId: tenant.org_id,
          rolesNamespace,
        })
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  return { config, loading, error }
}
