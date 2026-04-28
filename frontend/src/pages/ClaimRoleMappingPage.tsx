// PORTH-132 — Claim-to-role mapping screen and JWT test evaluator
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { usePorthContext } from '../context/PorthContext'
import { useHasRole } from '../hooks/useRoles'
import { PLATFORM_ADMIN } from '../constants'
import { claimConfigsApi } from '../api/claimConfigs'
import type { ClaimMappingConfig } from '../api/types'

const DEFAULT_MAPPING_SOURCE = {
  schema_version: '1',
  fields: {
    roles: {
      claim_key: 'https://porth.io/roles',
      ops: [{ op: 'resolve_roles' }],
    },
  },
  default_roles: [] as string[],
}

interface EvalResult {
  matchedRoles: string[]
  unmatchedKeys: string[]
}

function evaluateClaims(
  mappingSource: Record<string, unknown>,
  claimsJson: string,
): { result: EvalResult | null; error: string | null } {
  let claims: Record<string, unknown>
  try {
    claims = JSON.parse(claimsJson) as Record<string, unknown>
  } catch {
    return { result: null, error: 'Invalid JSON — check the claims input.' }
  }

  const fields = (mappingSource.fields ?? {}) as Record<
    string,
    { claim_key?: string; ops?: Array<{ op: string }> }
  >

  // Collect all claim_keys referenced by resolve_roles fields
  const referencedKeys = new Set<string>()
  const matchedRoles: string[] = []

  for (const fieldConfig of Object.values(fields)) {
    const hasResolveRoles = (fieldConfig.ops ?? []).some(o => o.op === 'resolve_roles')
    if (!hasResolveRoles || !fieldConfig.claim_key) continue

    referencedKeys.add(fieldConfig.claim_key)
    const claimValue = claims[fieldConfig.claim_key]
    if (Array.isArray(claimValue)) {
      for (const v of claimValue) {
        if (typeof v === 'string') matchedRoles.push(v)
      }
    }
  }

  const unmatchedKeys = Object.keys(claims).filter(k => !referencedKeys.has(k))

  return { result: { matchedRoles, unmatchedKeys }, error: null }
}

export default function ClaimRoleMappingPage() {
  const { currentUser } = usePorthContext()
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  const [searchParams] = useSearchParams()
  const tenantId = isPlatformAdmin
    ? (searchParams.get('tenantId') ?? '')
    : (currentUser?.porthUser.tenant_id ?? '')

  // Editor state
  const [config, setConfig] = useState<ClaimMappingConfig | null>(null)
  const [editorValue, setEditorValue] = useState<string>(
    JSON.stringify(DEFAULT_MAPPING_SOURCE, null, 2),
  )
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [saving, setSaving] = useState(false)
  const [jsonError, setJsonError] = useState<string | null>(null)

  // JWT evaluator state
  const [claimsInput, setClaimsInput] = useState('')
  const [evalResult, setEvalResult] = useState<EvalResult | null>(null)
  const [evalError, setEvalError] = useState<string | null>(null)

  useEffect(() => {
    if (!tenantId) {
      setLoadError('No tenantId in URL.')
      setLoading(false)
      return
    }
    claimConfigsApi
      .getLatest(tenantId)
      .then(cfg => {
        setConfig(cfg)
        setEditorValue(JSON.stringify(cfg.mapping_source, null, 2))
      })
      .catch(() => {
        // 404 or no config yet — keep default template
      })
      .finally(() => setLoading(false))
  }, [tenantId])

  function handleEditorChange(value: string) {
    setEditorValue(value)
    setJsonError(null)
    setSaveSuccess(false)
  }

  async function handleSave() {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(editorValue) as Record<string, unknown>
    } catch {
      setJsonError('Invalid JSON — fix the mapping config before saving.')
      return
    }

    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)
    try {
      const updated = await claimConfigsApi.create({
        tenant_id: tenantId,
        mapping_source: parsed,
      })
      setConfig(updated)
      setEditorValue(JSON.stringify(updated.mapping_source, null, 2))
      setSaveSuccess(true)
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  function handleEvaluate() {
    setEvalResult(null)
    setEvalError(null)

    let mappingSource: Record<string, unknown>
    try {
      mappingSource = JSON.parse(editorValue) as Record<string, unknown>
    } catch {
      setEvalError('Mapping config JSON is invalid — fix it before evaluating.')
      return
    }

    if (!claimsInput.trim()) {
      setEvalError('Paste JWT claims JSON first.')
      return
    }

    const { result, error } = evaluateClaims(mappingSource, claimsInput)
    if (error) {
      setEvalError(error)
    } else {
      setEvalResult(result)
    }
  }

  return (
    <div className="max-w-3xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Claim-to-Role Mappings</h1>
        <p className="text-gray-500 text-sm">
          Tenant: <span className="font-mono text-gray-700">{tenantId || '—'}</span>
        </p>
      </div>

      {/* ── Mapping JSON Editor ─────────────────────────────────────────── */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold text-gray-800">Mapping Config JSON</h2>

        {loadError && (
          <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {loadError}
          </div>
        )}

        {loading ? (
          <div className="animate-pulse bg-gray-200 rounded h-64 w-full" />
        ) : (
          <>
            <textarea
              className="font-mono w-full h-64 border border-gray-300 rounded p-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              value={editorValue}
              onChange={e => handleEditorChange(e.target.value)}
              spellCheck={false}
            />

            {jsonError && (
              <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
                {jsonError}
              </div>
            )}

            {config && (
              <div className="text-xs text-gray-500 space-x-4">
                <span>
                  Version: <span className="font-medium text-gray-700">{config.version}</span>
                </span>
                {config.compiled_hash && (
                  <span>
                    Hash:{' '}
                    <span className="font-mono text-gray-700">
                      {config.compiled_hash.slice(0, 8)}
                    </span>
                  </span>
                )}
              </div>
            )}

            <p className="text-xs text-gray-400">
              Edit the full mapping config JSON. Each save creates a new version.
            </p>

            {saveError && (
              <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
                {saveError}
              </div>
            )}

            {saveSuccess && (
              <div className="rounded-md bg-green-50 border border-green-200 px-3 py-2 text-sm text-green-700">
                Saved — new version created.
              </div>
            )}

            <button
              onClick={handleSave}
              disabled={saving || !tenantId}
              className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </>
        )}
      </section>

      {/* ── JWT Evaluator ───────────────────────────────────────────────── */}
      <section className="space-y-3 border-t border-gray-200 pt-6">
        <h2 className="text-base font-semibold text-gray-800">JWT Claims Evaluator</h2>
        <p className="text-xs text-gray-400">
          Client-side evaluation only — roles resolved against currently loaded mapping config.
        </p>

        <textarea
          className="font-mono w-full h-40 border border-gray-300 rounded p-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder='Paste decoded JWT claims as JSON…'
          value={claimsInput}
          onChange={e => {
            setClaimsInput(e.target.value)
            setEvalResult(null)
            setEvalError(null)
          }}
          spellCheck={false}
        />

        {evalError && (
          <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
            {evalError}
          </div>
        )}

        <button
          onClick={handleEvaluate}
          disabled={loading}
          className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50"
        >
          Evaluate
        </button>

        {evalResult && (
          <div className="space-y-4 pt-2">
            <div>
              <p className="text-sm font-medium text-gray-700 mb-2">Matched roles:</p>
              {evalResult.matchedRoles.length === 0 ? (
                <p className="text-sm text-gray-400">No roles matched.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {evalResult.matchedRoles.map(role => (
                    <span
                      key={role}
                      className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800"
                    >
                      {role}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div>
              <p className="text-sm font-medium text-gray-700 mb-2">Unmatched claim fields:</p>
              {evalResult.unmatchedKeys.length === 0 ? (
                <p className="text-sm text-gray-400">All claim fields are referenced.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {evalResult.unmatchedKeys.map(key => (
                    <span
                      key={key}
                      className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600"
                    >
                      {key}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
