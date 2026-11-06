// PORTH-656 — where the APIs are, on either shape (INSTALL.md §4a).
//
// Shared host (every slot today): CloudFront forwards /auth, /porth and /sample
// on the page's own origin, so every base is relative and the build env decides.
//
// Tenant-named hosts (VITE_TENANT_API_HOSTS=true): CloudFront serves the UI
// only, and the API is one `api` label deeper than the page:
//
//   page  https://acme.porth-dau.ems.estynsoftware.cloud
//   api   https://acme.api.porth-dau.ems.estynsoftware.cloud
//         ├── /sample/…   this app (root mapping)
//         └── /porth/…    Porth (the `porth` mapping key) — /porth/auth/* included
//
//   page  https://porth-dau.ems.estynsoftware.cloud   (the platform tenant)
//   api   https://api.porth-dau.ems.estynsoftware.cloud
//
// The session cookie is host-only on the API host, so everything that needs it
// (auth, Porth, the app) goes to that one host with credentials.

const TENANT_API_HOSTS = import.meta.env.VITE_TENANT_API_HOSTS === 'true'

/** The API origin for this page, or null on the shared-host shape. */
export function apiOrigin(location: Pick<Location, 'protocol' | 'hostname'> = window.location): string | null {
  if (!TENANT_API_HOSTS) return null
  const { protocol, hostname } = location
  const labels = hostname.split('.')
  // The platform apex is the slot itself: porth-dau.{zone} → api.porth-dau.{zone}.
  if (labels[0] === import.meta.env.VITE_PLATFORM_APEX) {
    return `${protocol}//api.${hostname}`
  }
  // A tenant: acme.{slot}.{zone} → acme.api.{slot}.{zone}.
  return `${protocol}//${[labels[0], 'api', ...labels.slice(1)].join('.')}`
}

/** Base for the Porth BFF routes (/auth/login|callback|me|logout). */
export function authBaseUrl(): string {
  const override = import.meta.env.VITE_AUTH_BASE_URL
  if (override !== undefined) return override.replace(/\/$/, '')
  const origin = apiOrigin()
  return origin ? `${origin}/porth` : ''
}

/** Base for the Porth API client. */
export function porthApiBaseUrl(): string {
  const origin = apiOrigin()
  return origin ? `${origin}/porth` : import.meta.env.VITE_API_BASE_URL
}

/**
 * Base for the sample app's client. The app serves its routes AT /sample, so
 * on an API host the base is the bare origin.
 *
 * Shared host: VITE_SAMPLE_APP_API_URL ?? VITE_API_BASE_URL, unchanged — the
 * set-but-empty VITE_SAMPLE_APP_API_URL is what keeps /sample on the page's own
 * origin (see deploy-sample-app.yml).
 */
export function sampleApiBaseUrl(): string {
  const origin = apiOrigin()
  if (origin) return origin
  return import.meta.env.VITE_SAMPLE_APP_API_URL ?? import.meta.env.VITE_API_BASE_URL
}
