// A new tenant, start to finish. A tenant is only usable once it has an identity
// provider, an admin role and a claim mapping: without the mapping the token's
// roles resolve to nothing and nobody can log in, not even its admin. So all of
// it is collected here, and nothing is created until the last step.
//
// Porth has no organization without a tenant. POST /organizations/ creates an
// org and its first tenant together, and PUT /tenants/ adds a tenant to an org
// that already exists (PORTH-197).
import { useState } from 'react'
import { organizationsApi } from '../api/organizations'
import { tenantsApi } from '../api/tenants'
import { claimConfigsApi } from '../api/claimConfigs'
import { DEFAULT_CLAIM_MAPPING } from '../constants'
import { EMPTY_IDP, IdpFields, idpFromForm, rolesClaimFor, type IdpForm } from './IdpFields'
import type { Organization, TenantTier } from '../api/types'

const TIERS: readonly TenantTier[] = ['production', 'staging', 'development', 'sandbox']
const STEPS = ['Organization', 'Tenant', 'Identity provider', 'Roles'] as const

/** The Organization choice that creates a new org along with the tenant. */
const NEW_ORG = '__new__'

const INPUT = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'
const LABEL = 'block text-sm font-medium text-gray-700 mb-1'
const HINT = 'mt-1 text-xs text-gray-400'

interface WizardForm extends IdpForm {
  org_id: string; org_name: string; org_slug: string
  tenant_id: string; display_name: string; tenant_tier: TenantTier
  /** null until the operator edits it, so it follows the provider and audience. */
  roles_claim: string | null
  admin_role_source_key: string
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : 'Failed'
}

/** A new tenant's claim mapping: Porth's template, reading roles from this tenant's claim. */
function mappingSource(rolesClaim: string): Record<string, unknown> {
  return {
    ...DEFAULT_CLAIM_MAPPING,
    fields: DEFAULT_CLAIM_MAPPING.fields.map(f => ({ ...f, source: rolesClaim })),
  }
}

export default function NewTenantWizard({ orgs, initialOrgId, onClose }: {
  orgs: Organization[]
  initialOrgId: string
  /** Called when the wizard closes, with a warning if it left a tenant unfinished. */
  onClose: (warning: string | null) => void
}) {
  const [step, setStep] = useState(0)
  const [form, setForm] = useState<WizardForm>({
    ...EMPTY_IDP, org_id: initialOrgId, org_name: '', org_slug: '', tenant_id: '', display_name: '',
    tenant_tier: 'production', roles_claim: null, admin_role_source_key: 'tenant-admin',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // What has been created so far. A retry resumes after these, so it never
  // creates the tenant twice, and once there is a tenant its details are fixed.
  const [done, setDone] = useState({ tenant: false, idp: false, claims: false })

  const rolesClaim = form.roles_claim ?? rolesClaimFor(form)

  function next(e: React.FormEvent) {
    e.preventDefault()
    setStep(s => s + 1)
  }

  async function create(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true); setError(null)
    const progress = { ...done }
    const tenant = {
      tenant_id: form.tenant_id.trim(), display_name: form.display_name, tenant_tier: form.tenant_tier,
      admin_role_source_key: form.admin_role_source_key.trim(),
    }
    try {
      if (!progress.tenant) {
        if (form.org_id === NEW_ORG) {
          await organizationsApi.create({ name: form.org_name, slug: form.org_slug, tenant })
        } else {
          await tenantsApi.create({ ...tenant, org_id: form.org_id })
        }
        progress.tenant = true
      }
      if (!progress.idp) {
        // Porth's create accepts idp_config_override and does not store it, so
        // the config always goes by PATCH, which does.
        await tenantsApi.update(tenant.tenant_id, { idp_config_override: idpFromForm(form) })
        progress.idp = true
      }
      if (!progress.claims) {
        await claimConfigsApi.create({ tenant_id: tenant.tenant_id, mapping_source: mappingSource(rolesClaim.trim()) })
        progress.claims = true
      }
      onClose(null)
    } catch (e: unknown) {
      setDone(progress)
      setError(!progress.tenant
        ? `The tenant was not created: ${message(e)}`
        : `${tenant.tenant_id} was created, but its ${progress.idp ? 'claim mapping' : 'identity provider'} was not saved: ${message(e)}. Retry to finish it.`)
    } finally {
      setSaving(false)
    }
  }

  function cancel() {
    if (done.tenant) {
      onClose(`${form.tenant_id.trim()} was created, but has no ${done.idp ? 'claim mapping' : 'identity provider or claim mapping'}, so nobody can log in to it. ${done.idp ? 'Use Manage' : 'Use Edit and Manage'} to finish it.`)
    } else {
      onClose(null)
    }
  }

  const navigation = (
    <div className="flex justify-between gap-3 pt-2">
      <button type="button" onClick={cancel} className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50">Cancel</button>
      <div className="flex gap-3">
        {step > 0 && !done.tenant && (
          <button type="button" onClick={() => setStep(s => s - 1)} disabled={saving} className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">Back</button>
        )}
        {step < STEPS.length - 1
          ? <button type="submit" className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700">Next</button>
          : <button type="submit" disabled={saving} className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50">
              {saving ? 'Creating…' : done.tenant ? 'Retry' : 'Create'}
            </button>}
      </div>
    </div>
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-semibold text-gray-900 mb-1">New Tenant</h2>
        <p className="text-xs text-gray-400 mb-4">Step {step + 1} of {STEPS.length}: {STEPS[step]}</p>
        {error && <div role="alert" className="mb-3 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>}

        {step === 0 && (
          <form onSubmit={next} className="space-y-4">
            <div>
              <label htmlFor="nt-org" className={LABEL}>Organization</label>
              <select id="nt-org" required value={form.org_id}
                onChange={e => setForm(f => ({ ...f, org_id: e.target.value }))} className={INPUT}>
                <option value="">Select an organization…</option>
                {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                <option value={NEW_ORG}>+ New organization…</option>
              </select>
            </div>
            {form.org_id === NEW_ORG && (
              <>
                <div>
                  <label htmlFor="nt-org-name" className={LABEL}>Organization Name</label>
                  <input id="nt-org-name" type="text" required value={form.org_name}
                    onChange={e => setForm(f => ({ ...f, org_name: e.target.value }))} className={INPUT} />
                </div>
                <div>
                  <label htmlFor="nt-org-slug" className={LABEL}>Slug</label>
                  <input id="nt-org-slug" type="text" required value={form.org_slug}
                    onChange={e => setForm(f => ({ ...f, org_slug: e.target.value }))}
                    placeholder="e.g. acme" className={`${INPUT} font-mono`} />
                </div>
              </>
            )}
            {navigation}
          </form>
        )}

        {step === 1 && (
          <form onSubmit={next} className="space-y-4">
            <div>
              <label htmlFor="nt-tid" className={LABEL}>Tenant ID</label>
              <input id="nt-tid" type="text" required value={form.tenant_id}
                onChange={e => setForm(f => ({ ...f, tenant_id: e.target.value }))}
                placeholder="e.g. acme-prod" className={`${INPUT} font-mono`} />
              <p className={HINT}>Cannot be changed after creation.</p>
            </div>
            <div>
              <label htmlFor="nt-dn" className={LABEL}>Display Name</label>
              <input id="nt-dn" type="text" required value={form.display_name}
                onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))} className={INPUT} />
            </div>
            <div>
              <label htmlFor="nt-env" className={LABEL}>Tenant Tier</label>
              <select id="nt-env" value={form.tenant_tier}
                onChange={e => setForm(f => ({ ...f, tenant_tier: e.target.value as TenantTier }))} className={INPUT}>
                {TIERS.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
              <p className={HINT}>A label on the tenant — not the environment it lives in, which comes from the host.</p>
            </div>
            {navigation}
          </form>
        )}

        {step === 2 && (
          <form onSubmit={next} className="space-y-4">
            <IdpFields prefix="nt" form={form} setForm={setForm} />
            {navigation}
          </form>
        )}

        {step === 3 && (
          <form onSubmit={create} className="space-y-4">
            <p className="text-sm text-gray-600">Without these, nobody can log in to this tenant, not even its admin.</p>
            <div>
              <label htmlFor="nt-claim" className={LABEL}>Roles Claim</label>
              <input id="nt-claim" type="text" required value={rolesClaim} disabled={done.claims}
                onChange={e => setForm(f => ({ ...f, roles_claim: e.target.value }))} className={`${INPUT} font-mono`} />
              <p className={HINT}>The claim in your identity provider's token that lists the user's roles.</p>
            </div>
            <div>
              <label htmlFor="nt-arsk" className={LABEL}>Admin Role Value</label>
              <input id="nt-arsk" type="text" required value={form.admin_role_source_key} disabled={done.tenant}
                onChange={e => setForm(f => ({ ...f, admin_role_source_key: e.target.value }))}
                placeholder="e.g. tenant-admin" className={`${INPUT} font-mono`} />
              <p className={HINT}>The value in that claim that makes someone this tenant's admin. Your identity provider must send it for them.</p>
            </div>
            {navigation}
          </form>
        )}
      </div>
    </div>
  )
}
