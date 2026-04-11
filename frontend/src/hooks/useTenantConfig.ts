import { useState, useEffect } from 'react'

// Default claim namespace used by the Porth platform Auth0 Action.
// Can be overridden per-tenant via idp_config_override.custom_claims.roles_namespace.
const DEFAULT_ROLES_NAMESPACE = 'https://porth.io/roles'

export interface TenantIdpConfig {
  tenantId: string
  organizationId: string
  domain: string
  clientId: string
  audience?: string
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
  // URL rather than a customer tenant subdomain), use the platform tenant so
  // the UI picks up platform-level IdP configuration.
  const platformApex = import.meta.env.VITE_PLATFORM_APEX
  if (platformApex && subdomain === platformApex) {
    return 'platform'
  }

  return subdomain
}

export function useTenantConfig(): {
  config: TenantIdpConfig | null
  loading: boolean
  error: string | null
} {
  const [config, setConfig] = useState<TenantIdpConfig | null>(null)
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

    fetch(`${apiBase}/tenants/${encodeURIComponent(tenantId)}`)
      .then(res => {
        if (!res.ok) throw new Error(`Tenant lookup failed: ${res.status}`)
        return res.json()
      })
      .then(tenant => {
        const idp = tenant.idp_config_override ?? null
        if (!idp?.domain || !idp?.client_id) {
          throw new Error(`Tenant ${tenantId} has no IdP configuration`)
        }

        // Read the roles claim namespace from the tenant's IdP config if
        // the operator has configured it; fall back to the platform default.
        // The Auth0 Action (or equivalent IdP hook) must use the same namespace.
        const rolesNamespace =
          idp.custom_claims?.roles_namespace ?? DEFAULT_ROLES_NAMESPACE

        setConfig({
          tenantId,
          // Porth Tenant model uses org_id (not organization_id)
          organizationId: tenant.org_id,
          domain: idp.domain,
          clientId: idp.client_id,
          audience: idp.audience,
          rolesNamespace,
        })
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  return { config, loading, error }
}
