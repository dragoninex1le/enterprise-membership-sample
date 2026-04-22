// Role name constants — these must match what the Porth bootstrap creates and
// what the IdP Action injects into the JWT via the claim mapping.
// Centralised here to avoid duplication across router, sidebar, and hooks.

/** The Porth platform-level role assigned to Estyn operators. */
export const PLATFORM_ADMIN = 'platform-admin'
