/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  readonly VITE_DEV_TENANT_ID: string
  readonly VITE_SAMPLE_APP_API_URL?: string
  readonly VITE_PLATFORM_APEX?: string
  readonly VITE_AUTH_BASE_URL?: string
  readonly VITE_ROLES_NAMESPACE?: string
  readonly VITE_E2E_AUTH?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
