// PORTH-132 — test a token's claims against a claim mapping. Folded into the claim mapping page:
// a tester is only meaningful next to the mapping it tests, for one tenant.
import { useState } from 'react'

interface EvalResult {
  matchedRoles: string[]
  unmatchedKeys: string[]
}

export function evaluateClaims(
  mappingSource: Record<string, unknown>,
  claimsJson: string,
): { result: EvalResult | null; error: string | null } {
  let claims: Record<string, unknown>
  try {
    claims = JSON.parse(claimsJson) as Record<string, unknown>
  } catch {
    return { result: null, error: 'Invalid JSON — check the claims input.' }
  }

  // Porth's schema 2.0 lists fields as an array naming the claim in `source`; the
  // older shape keyed an object by field name with `claim_key`. Read both. Read
  // only the old one and a real 2.0 config — all Porth now stores — evaluates to
  // no roles on this page while resolving roles correctly on the server.
  type FieldConfig = { source?: string; claim_key?: string; ops?: Array<{ op: string }> }
  const rawFields = mappingSource.fields ?? []
  const fields: FieldConfig[] = Array.isArray(rawFields)
    ? (rawFields as FieldConfig[])
    : Object.values(rawFields as Record<string, FieldConfig>)

  // Collect all claim keys referenced by resolve_roles fields
  const referencedKeys = new Set<string>()
  const matchedRoles: string[] = []

  for (const fieldConfig of fields) {
    const claimKey = fieldConfig.source ?? fieldConfig.claim_key
    const hasResolveRoles = (fieldConfig.ops ?? []).some(o => o.op === 'resolve_roles')
    if (!hasResolveRoles || !claimKey) continue

    referencedKeys.add(claimKey)
    const claimValue = claims[claimKey]
    if (Array.isArray(claimValue)) {
      for (const v of claimValue) {
        if (typeof v === 'string') matchedRoles.push(v)
      }
    }
  }

  const unmatchedKeys = Object.keys(claims).filter(k => !referencedKeys.has(k))

  return { result: { matchedRoles, unmatchedKeys }, error: null }
}

/** `mapping` is the editor's text: the tester evaluates what is there now, saved or not. */
export default function TokenTester({ mapping }: { mapping: string }) {
  const [claimsInput, setClaimsInput] = useState('')
  const [evalResult, setEvalResult] = useState<EvalResult | null>(null)
  const [evalError, setEvalError] = useState<string | null>(null)

  function handleEvaluate() {
    setEvalResult(null)
    setEvalError(null)

    let mappingSource: Record<string, unknown>
    try {
      mappingSource = JSON.parse(mapping) as Record<string, unknown>
    } catch {
      setEvalError('The mapping JSON is invalid — fix it before testing a token.')
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
    <section className="space-y-3 border-t border-gray-200 pt-6">
        <h2 className="text-base font-semibold text-gray-800">Test a token</h2>
        <p className="text-xs text-gray-400">
          Paste a token's decoded claims to see which roles this mapping gives it. Evaluated here in the
          browser, against the mapping as it stands in the editor - saved or not.
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
  )
}
