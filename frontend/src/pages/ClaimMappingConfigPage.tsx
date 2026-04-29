// PORTH-131 — Claim mapping configuration screen
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { usePorthContext } from '../context/PorthContext'
import { useHasRole } from '../hooks/useRoles'
import { PLATFORM_ADMIN } from '../constants'
import { claimConfigsApi } from '../api/claimConfigs'
import type { ClaimMappingConfig } from '../api/types'

const DEFAULT_MAPPING = JSON.stringify(
  {
    schema_version: '1',
    fields: {
      roles: {
        claim_key: 'https://porth.io/roles',
        ops: [{ op: 'resolve_roles' }],
      },
    },
    default_roles: [],
  },
  null,
  2,
)

export default function ClaimMappingConfigPage() {
  const { currentUser } = usePorthContext()
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  const [searchParams] = useSearchParams()
  const tenantId = isPlatformAdmin
    ? (searchParams.get('tenantId') ?? '')
    : (currentUser?.porthUser.tenant_id ?? '')

  // Editor state
  const [editorValue, setEditorValue] = useState<string>(DEFAULT_MAPPING)
  const [current, setCurrent] = useState<ClaimMappingConfig | null>(null)
  const [editorLoading, setEditorLoading] = useState(false)
  const [editorError, setEditorError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // Version history state
  const [versions, setVersions] = useState<ClaimMappingConfig[]>([])
  const [versionsLoading, setVersionsLoading] = useState(false)
  const [versionsError, setVersionsError] = useState<string | null>(null)

  const loadLatest = () => {
    if (!tenantId) return
    setEditorLoading(true)
    setEditorError(null)
    claimConfigsApi
      .getLatest(tenantId)
      .then((config) => {
        setCurrent(config)
        setEditorValue(JSON.stringify(config.mapping_source, null, 2))
      })
      .catch((err) => {
        const status = err?.response?.status
        if (status !== 404) {
          setEditorError('Failed to load current config.')
        }
        setCurrent(null)
      })
      .finally(() => setEditorLoading(false))
  }

  const loadVersions = () => {
    if (!tenantId) return
    setVersionsLoading(true)
    setVersionsError(null)
    claimConfigsApi
      .listVersions(tenantId)
      .then(setVersions)
      .catch(() => setVersionsError('Failed to load version history.'))
      .finally(() => setVersionsLoading(false))
  }

  useEffect(() => {
    if (tenantId) {
      loadLatest()
      loadVersions()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId])

  const handleSave = async () => {
    if (!tenantId) {
      setSaveError('Select a tenant before saving.')
      return
    }
    setSaveError(null)
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(editorValue)
    } catch {
      setSaveError('Invalid JSON — please fix syntax errors before saving.')
      return
    }
    setSaving(true)
    try {
      await claimConfigsApi.create({ tenant_id: tenantId, mapping_source: parsed })
      loadLatest()
      loadVersions()
    } catch {
      setSaveError('Save failed. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const handleRollback = async (version: number) => {
    if (!window.confirm(`Roll back to version ${version}?`)) return
    try {
      await claimConfigsApi.rollback(tenantId, version)
      loadLatest()
      loadVersions()
    } catch {
      setEditorError(`Rollback to version ${version} failed.`)
    }
  }

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    })

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Claim Mapping Config</h1>

      {!tenantId && (
        <div className="mb-4 px-4 py-3 bg-yellow-50 border border-yellow-200 text-yellow-800 rounded text-sm">
          Add <span className="font-mono">?tenantId=your-tenant-id</span> to the URL to load or save a config.
        </div>
      )}

      <div className="flex gap-6 items-start">
        {/* ── Left: Editor (2/3) ── */}
        <div className="flex-[2] min-w-0">
          {editorError && (
            <div className="mb-4 px-4 py-3 bg-red-50 border border-red-300 text-red-700 rounded text-sm">
              {editorError}
            </div>
          )}

          {editorLoading ? (
            <div className="animate-pulse bg-gray-200 rounded h-64 w-full" />
          ) : (
            <>
              <textarea
                className="font-mono w-full h-64 border rounded p-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                value={editorValue}
                onChange={(e) => {
                  setEditorValue(e.target.value)
                  setSaveError(null)
                }}
                spellCheck={false}
              />

              {saveError && (
                <p className="mt-1 text-red-600 text-xs">{saveError}</p>
              )}

              {current && (
                <p className="mt-1 text-xs text-gray-400">
                  Version {current.version}
                  {current.compiled_hash && (
                    <> &middot; hash <span className="font-mono">{current.compiled_hash.slice(0, 8)}</span></>
                  )}
                </p>
              )}

              <div className="mt-3 flex gap-2">
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50"
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
                <button
                  onClick={() => alert('Compile preview not yet available')}
                  className="px-4 py-2 bg-gray-100 text-gray-700 text-sm rounded-lg hover:bg-gray-200 border border-gray-300"
                >
                  Compile Preview
                </button>
              </div>
            </>
          )}
        </div>

        {/* ── Right: Version History (1/3) ── */}
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Version History</h2>

          {versionsError && (
            <div className="mb-3 px-3 py-2 bg-red-50 border border-red-300 text-red-700 rounded text-xs">
              {versionsError}
            </div>
          )}

          {versionsLoading ? (
            <div className="space-y-2">
              <div className="animate-pulse bg-gray-200 rounded h-6 w-full" />
              <div className="animate-pulse bg-gray-200 rounded h-6 w-full" />
              <div className="animate-pulse bg-gray-200 rounded h-6 w-full" />
            </div>
          ) : versions.length === 0 ? (
            <p className="text-xs text-gray-400">{tenantId ? 'No versions yet.' : 'Select a tenant to view history.'}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="pb-1 pr-3 font-medium text-gray-500">Ver</th>
                    <th className="pb-1 pr-3 font-medium text-gray-500">Created</th>
                    <th className="pb-1 pr-3 font-medium text-gray-500">Hash</th>
                    <th className="pb-1 font-medium text-gray-500"></th>
                  </tr>
                </thead>
                <tbody>
                  {versions.map((v) => (
                    <tr key={v.id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-1.5 pr-3 font-mono text-gray-700">{v.version}</td>
                      <td className="py-1.5 pr-3 text-gray-500 whitespace-nowrap">{formatDate(v.created_at)}</td>
                      <td className="py-1.5 pr-3 font-mono text-gray-500">
                        {v.compiled_hash ? v.compiled_hash.slice(0, 8) : '—'}
                      </td>
                      <td className="py-1.5">
                        <button
                          onClick={() => handleRollback(v.version)}
                          className="text-indigo-600 hover:text-indigo-800 hover:underline"
                        >
                          Rollback
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
