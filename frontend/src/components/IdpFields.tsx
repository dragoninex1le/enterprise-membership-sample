import { ROLES_NAMESPACE } from '../constants'
import type { TenantIdpConfig } from '../api/types'

/** Every tenant has an identity provider: Porth has no other way to log in.
 * A new provider is a row here and a case in `idpFromForm`. */
export type IdpProvider = 'auth0' | 'keycloak'
export const IDP_PROVIDERS: readonly { id: IdpProvider; label: string }[] = [
  { id: 'auth0', label: 'Auth0' },
  { id: 'keycloak', label: 'Keycloak' },
]
export interface IdpForm {
  idp_provider: IdpProvider; idp_domain: string; idp_realm: string
  idp_client_id: string; idp_audience: string; idp_org_id: string
}

export const EMPTY_IDP: IdpForm = { idp_provider: 'auth0', idp_domain: '', idp_realm: '', idp_client_id: '', idp_audience: '', idp_org_id: '' }

/** Where this provider's tokens normally carry roles: what a new tenant's claim mapping starts from.
 *
 * Auth0 namespaces custom claims, and EMS's convention is <audience>/roles (PORTH-591).
 * Keycloak puts realm roles in realm_access.roles, which Porth resolves as a dotted path.
 */
export function rolesClaimFor(f: IdpForm): string {
  if (f.idp_provider === 'keycloak') return 'realm_access.roles'
  const audience = f.idp_audience.trim().replace(/\/+$/, '')
  return audience ? `${audience}/roles` : ROLES_NAMESPACE
}

/** The Auth0 domain an operator typed, reduced to the host it names. */
function hostOf(domain: string): string {
  return domain.trim().replace(/^https?:\/\//, '').replace(/\/.*$/, '')
}

/** The Keycloak server address an operator typed, with its scheme and no trailing slash. */
function serverOf(address: string): string {
  const a = address.trim().replace(/\/+$/, '')
  return /^https?:\/\//.test(a) ? a : `https://${a}`
}

/** Porth's neutral OIDC config, built from the form's fields for the chosen provider.
 *
 * Porth replaced `{ provider, domain }` with `{ issuer, jwks_uri, client_id,
 * protocol }` (PORTH-488/S5) and ignores fields it does not know. The old body
 * therefore lost its IdP silently and the create failed 422 on the fields that
 * were missing.
 *
 * `protocol` is not optional in practice: the server defaults it to "oidc",
 * which would store an Auth0 tenant as generic OIDC without the authorize and
 * token endpoints its login needs. The create would succeed; the first login
 * would not. `issuer` keeps its trailing slash — it has to equal the token's
 * `iss`, and Auth0 issues `https://{domain}/`.
 *
 * `provider_org_id` is what makes a tenant login a TENANT login. Porth's auth
 * proxy maps the host a user logs in at to this id and sends it to Auth0 as the
 * organization; resolution then keys on (issuer, client_id, provider_org_id).
 * Left empty on a tenant that shares its Auth0 app with the platform tenant, the
 * login is unscoped and resolves to platform.
 *
 * Keycloak is generic OIDC to Porth, which composes nothing for "oidc", so all
 * four addresses are spelled out from the server and realm.
 *
 * `base` is the tenant's existing config when editing. PATCH replaces the whole
 * object, so fields this form never shows are carried over rather than wiped by
 * an edit to the audience. Not across a change of provider: the old provider's
 * endpoints would be wrong for the new one.
 */
export function idpFromForm(f: IdpForm, base?: TenantIdpConfig): TenantIdpConfig {
  const kept = base && providerOf(base) === f.idp_provider ? base : undefined
  const shared = { client_id: f.idp_client_id, audience: f.idp_audience || undefined }
  switch (f.idp_provider) {
    case 'auth0': {
      const host = hostOf(f.idp_domain)
      return {
        ...kept, ...shared,
        protocol: 'auth0',
        issuer: `https://${host}/`,
        jwks_uri: `https://${host}/.well-known/jwks.json`,
        provider_org_id: f.idp_org_id.trim() || undefined,
      }
    }
    case 'keycloak': {
      const issuer = `${serverOf(f.idp_domain)}/realms/${f.idp_realm.trim()}`
      return {
        ...kept, ...shared,
        // PORTH-669: the provider type. Porth signs this tenant in through
        // Keycloak itself, asks for the organization as scope
        // organization:<alias> and reads it back from the `organization` claim.
        protocol: 'keycloak',
        issuer,
        jwks_uri: `${issuer}/protocol/openid-connect/certs`,
        authorization_endpoint: `${issuer}/protocol/openid-connect/auth`,
        token_endpoint: `${issuer}/protocol/openid-connect/token`,
        end_session_endpoint: `${issuer}/protocol/openid-connect/logout`,
        revocation_endpoint: `${issuer}/protocol/openid-connect/revoke`,
        provider_org_id: f.idp_org_id.trim() || undefined,
      }
    }
  }
}

/** Which provider a stored config belongs to: its provider type, or — for a
 * Keycloak tenant saved as generic "oidc" before PORTH-669 — an issuer ending in a realm. */
function providerOf(cfg?: TenantIdpConfig): IdpProvider {
  if (cfg?.protocol === 'keycloak') return 'keycloak'
  return cfg?.protocol !== 'auth0' && /\/realms\/[^/]+\/?$/.test(cfg?.issuer ?? '') ? 'keycloak' : 'auth0'
}

/** The form's fields for a stored config, when editing. */
export function idpFormOf(cfg?: TenantIdpConfig): IdpForm {
  const provider = providerOf(cfg)
  const [server, realm] = provider === 'keycloak' ? (cfg?.issuer ?? '').replace(/\/$/, '').split('/realms/') : ['', '']
  return {
    idp_provider: provider,
    idp_domain: provider === 'keycloak' ? server : domainOf(cfg),
    idp_realm: realm,
    idp_client_id: cfg?.client_id ?? '',
    idp_audience: cfg?.audience ?? '',
    idp_org_id: cfg?.provider_org_id ?? '',
  }
}

/** The domain to show when editing: the issuer's host, or a pre-PORTH-488 record's `domain`. */
function domainOf(cfg?: TenantIdpConfig): string {
  if (!cfg) return ''
  try {
    if (cfg.issuer) return new URL(cfg.issuer).host
  } catch {
    // not a URL — fall through to the legacy field
  }
  return (cfg as unknown as { domain?: string }).domain ?? ''
}

export function IdpFields<T extends IdpForm>(
  { prefix, form, setForm }: { prefix: string; form: T; setForm: (fn: (f: T) => T) => void }
) {
  const input = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500'
  const keycloak = form.idp_provider === 'keycloak'
  return (
    <div className="border-t border-gray-100 pt-4 space-y-3">
      <div>
        <label htmlFor={`${prefix}-provider`} className="block text-sm font-medium text-gray-700 mb-1">Identity Provider</label>
        <select id={`${prefix}-provider`} value={form.idp_provider}
          onChange={e => setForm(f => ({ ...f, idp_provider: e.target.value as IdpProvider }))}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
          {IDP_PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor={`${prefix}-domain`} className="block text-sm font-medium text-gray-700 mb-1">{keycloak ? 'Server URL' : 'Domain'}</label>
        <input id={`${prefix}-domain`} type="text" required value={form.idp_domain}
          onChange={e => setForm(f => ({ ...f, idp_domain: e.target.value }))}
          placeholder={keycloak ? 'https://keycloak.example.com' : 'your-tenant.auth0.com'}
          className={input} />
      </div>
      {keycloak && (
        <div>
          <label htmlFor={`${prefix}-realm`} className="block text-sm font-medium text-gray-700 mb-1">Realm</label>
          <input id={`${prefix}-realm`} type="text" required value={form.idp_realm}
            onChange={e => setForm(f => ({ ...f, idp_realm: e.target.value }))}
            className={input} />
        </div>
      )}
      <div>
        <label htmlFor={`${prefix}-cid`} className="block text-sm font-medium text-gray-700 mb-1">Client ID</label>
        <input id={`${prefix}-cid`} type="text" required value={form.idp_client_id}
          onChange={e => setForm(f => ({ ...f, idp_client_id: e.target.value }))}
          className={input} />
      </div>
      <div>
        <label htmlFor={`${prefix}-aud`} className="block text-sm font-medium text-gray-700 mb-1">Audience <span className="text-gray-400 font-normal">(optional)</span></label>
        <input id={`${prefix}-aud`} type="text" value={form.idp_audience}
          onChange={e => setForm(f => ({ ...f, idp_audience: e.target.value }))}
          placeholder="https://your-api.example.com"
          className={input} />
      </div>
      {keycloak && (
        <div>
          <label htmlFor={`${prefix}-idp-org`} className="block text-sm font-medium text-gray-700 mb-1">Organization alias</label>
          <input id={`${prefix}-idp-org`} type="text" value={form.idp_org_id}
            onChange={e => setForm(f => ({ ...f, idp_org_id: e.target.value }))}
            className={input} />
          <p className="mt-1 text-xs text-gray-400">The Keycloak organization this tenant's users belong to. Logins are scoped to it, and a token for any other organization is refused.</p>
        </div>
      )}
      {!keycloak && (
        <div>
          <label htmlFor={`${prefix}-idp-org`} className="block text-sm font-medium text-gray-700 mb-1">Auth0 Organization ID</label>
          <input id={`${prefix}-idp-org`} type="text" value={form.idp_org_id}
            onChange={e => setForm(f => ({ ...f, idp_org_id: e.target.value }))}
            placeholder="org_…"
            pattern="org_[A-Za-z0-9]+"
            title="An Auth0 Organization ID, e.g. org_AbC123"
            className={input} />
          <p className="mt-1 text-xs text-gray-400">Needed when this Auth0 app is shared with other tenants. Without it, logging in at this tenant's address lands in the platform tenant.</p>
        </div>
      )}
    </div>
  )
}
