/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  readonly VITE_DEV_TENANT_ID: string
  readonly VITE_SAMPLE_APP_API_URL?: string
  readonly VITE_PLATFORM_APEX?: string
  readonly VITE_AUTH_BASE_URL?: string
  readonly VITE_ROLES_NAMESPACE?: string
  readonly VITE_E2E_AUTH?: string
  /** PORTH-656: 'true' on a tenant-API-host slot — see src/lib/apiHost.ts. */
  readonly VITE_TENANT_API_HOSTS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
