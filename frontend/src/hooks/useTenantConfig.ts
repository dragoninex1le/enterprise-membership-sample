import { useState, useEffect } from 'react'

export interface TenantIdpConfig {
  tenantId: string
  domain: string
  clientId: string
  audience: string
}

function getTenantIdFromSubdomain(): string | null {
  const hostname = window.location.hostname
  // localhost / 127.0.0.1 — fall back to env var for dev
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return import.meta.env.VITE_DEV_TENANT_ID ?? null
  }
  // {tenant-id}.example.com → tenant-id
  const parts = hostname.split('.')
  return parts.length >= 3 ? parts[0] : null
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
    fetch(`${apiBase}/tenants/${encodeURIComponent(tenantId)}`)
      .then(res => {
        if (!res.ok) throw new Error(`Tenant lookup failed: ${res.status}`)
        return res.json()
      })
      .then(tenant => {
        const idp = tenant.idp_config_override ?? null
        if (!idp?.issuer || !idp?.client_id || !idp?.audience) {
          throw new Error(`Tenant ${tenantId} has no IdP configuration`)
        }
        // Auth0 issuer is https://{domain}/ — extract the domain
        const domain = idp.issuer.replace(/^https?:\/\//, '').replace(/\/$/, '')
        setConfig({ tenantId, domain, clientId: idp.client_id, audience: idp.audience })
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  return { config, loading, error }
}
