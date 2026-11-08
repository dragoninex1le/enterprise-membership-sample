// The session-bound bearer test: does signing out end a token this session handed out?
//
//   1. Get this session's token and copy it.
//   2. Sign out, sign back in, and paste the OLD token into "Call with a token".
//   3. EMS's bearer route should refuse it: Porth's authorizer ends a handed-out
//      token with its session (session_ended), whatever the token's exp says.
//      Auth0's /userinfo shows whether the IdP itself still accepts it — an access
//      token is a signed JWT, and the IdP revokes refresh tokens, not those.
//
// The token is shown on purpose (the test is to carry it across a sign-out). It is
// held in this page's state only: never stored, logged or put in a URL.
import { useState } from 'react'
import {
  callWithToken, curlCommand, fetchSessionToken, jwtClaims, userinfoUrl, whoamiUrl,
  type CallResult, type SessionToken,
} from '../lib/bearerToken'

const card = 'bg-white border border-gray-200 rounded-lg p-5 mb-5'
const button = 'px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700 disabled:opacity-50'
const plain = 'px-3 py-1.5 border border-gray-300 rounded-lg text-sm hover:bg-gray-50'
const mono = 'w-full font-mono text-xs border border-gray-300 rounded-lg p-2 break-all'

const CLAIMS = ['iss', 'aud', 'sub', 'org_id', 'iat', 'exp']

function when(seconds: unknown): string {
  return typeof seconds === 'number' ? `${new Date(seconds * 1000).toISOString()} (${seconds})` : String(seconds)
}

function Claims({ token }: { token: string }) {
  const claims = jwtClaims(token)
  if (!claims) return <p className="text-sm text-gray-500">Not a JWT.</p>
  const exp = claims.exp
  const expired = typeof exp === 'number' && exp * 1000 < Date.now()
  return (
    <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1 text-xs">
      {CLAIMS.filter(k => k in claims).map(k => (
        <div key={k} className="contents">
          <dt className="text-gray-500">{k}</dt>
          <dd className="font-mono break-all">
            {k === 'iat' || k === 'exp' ? when(claims[k]) : JSON.stringify(claims[k])}
          </dd>
        </div>
      ))}
      <dt className="text-gray-500">own expiry</dt>
      <dd className={expired ? 'text-red-600' : 'text-green-700'}>
        {expired ? 'expired by its own exp' : 'not yet expired by its own exp'}
      </dd>
    </dl>
  )
}

function Result({ label, result, curl }: { label: string; result: CallResult | null; curl: string }) {
  if (!result) return null
  const ok = result.status >= 200 && result.status < 300
  return (
    <div className="mt-3 border-t border-gray-100 pt-3">
      <p className="text-sm font-medium">
        {label}:{' '}
        <span className={ok ? 'text-green-700' : 'text-red-600'}>
          {result.status === 0 ? 'no readable answer' : `${result.status} ${ok ? 'accepted' : 'refused'}`}
        </span>
        {result.at && <span className="text-gray-400 font-normal"> at {result.at}</span>}
      </p>
      {result.unreadable && <p className="text-xs text-gray-600 mt-1">{result.unreadable}</p>}
      {result.body !== null && result.body !== '' && (
        <pre className="mt-2 bg-gray-50 rounded p-2 text-xs overflow-auto">{JSON.stringify(result.body, null, 2)}</pre>
      )}
      <p className="text-xs text-gray-500 mt-2">From a terminal:</p>
      <pre className="bg-gray-50 rounded p-2 text-xs overflow-auto whitespace-pre-wrap break-all">{curl}</pre>
    </div>
  )
}

export default function BearerTokenPage() {
  const [token, setToken] = useState<SessionToken | null>(null)
  const [fetchResult, setFetchResult] = useState<CallResult | null>(null)
  const [pasted, setPasted] = useState('')
  const [ems, setEms] = useState<CallResult | null>(null)
  const [idp, setIdp] = useState<CallResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  const issuer = jwtClaims(pasted)?.iss
  const target = whoamiUrl()

  async function getToken() {
    setBusy(true)
    setCopied(false)
    const r = await fetchSessionToken()
    setToken(r.token ?? null)
    setFetchResult(r.token ? null : r)
    setBusy(false)
  }

  async function copy() {
    if (!token) return
    await navigator.clipboard.writeText(token.access_token)
    setCopied(true)
  }

  async function callEms() {
    setBusy(true)
    setEms(await callWithToken(target, pasted))
    setBusy(false)
  }

  async function callIdp() {
    if (typeof issuer !== 'string') return
    setBusy(true)
    setIdp(await callWithToken(userinfoUrl(issuer), pasted))
    setBusy(false)
  }

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Bearer token test</h1>
      <p className="text-sm text-gray-600 mb-5">
        Does signing out end a token this session handed out? Get the token and copy it, sign out,
        sign back in, then paste the old token below — without getting a new one.
      </p>

      <section className={card} aria-label="This session's token">
        <h2 className="text-lg font-semibold mb-1">1. This session's token</h2>
        <p className="text-xs text-amber-700 mb-3">
          This is your live access token. Copy it for this test only.
        </p>
        <button className={button} onClick={getToken} disabled={busy}>Get token</button>
        {fetchResult && (
          <p className="text-sm text-red-600 mt-3">
            /porth/auth/token answered {fetchResult.status}: {JSON.stringify(fetchResult.body)}
          </p>
        )}
        {token && (
          <div className="mt-3 space-y-2">
            <textarea className={mono} rows={5} readOnly value={token.access_token} aria-label="Access token" />
            <div className="flex items-center gap-3">
              <button className={plain} onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
              <button className={plain} onClick={() => setPasted(token.access_token)}>Use it below</button>
              <span className="text-xs text-gray-500">
                {token.token_type}, Porth's expires_at {when(token.expires_at)}
              </span>
            </div>
            <Claims token={token.access_token} />
          </div>
        )}
      </section>

      <section className={card} aria-label="Call with a token">
        <h2 className="text-lg font-semibold mb-1">2. Call with a token</h2>
        <p className="text-sm text-gray-600 mb-3">
          Paste a token. The calls send exactly that token and no cookie.
        </p>
        <textarea
          className={mono} rows={5} value={pasted} placeholder="eyJ…"
          onChange={e => { setPasted(e.target.value); setEms(null); setIdp(null) }}
          aria-label="Token to call with"
        />
        {pasted.trim() && <div className="mt-2"><Claims token={pasted} /></div>}
        <div className="flex flex-wrap gap-3 mt-3">
          <button className={button} onClick={callEms} disabled={busy || !pasted.trim()}>
            Call EMS's bearer route (Porth decides)
          </button>
          <button className={button} onClick={callIdp} disabled={busy || typeof issuer !== 'string'}>
            Ask the IdP (/userinfo)
          </button>
        </div>
        <Result label={`EMS ${target}`} result={ems} curl={curlCommand(target, pasted || '<token>')} />
        {typeof issuer === 'string' && (
          <Result label={`IdP ${userinfoUrl(issuer)}`} result={idp} curl={curlCommand(userinfoUrl(issuer), pasted)} />
        )}
      </section>

      <section className={card} aria-label="What to expect">
        <h2 className="text-lg font-semibold mb-2">What to expect</h2>
        <ul className="text-sm text-gray-700 list-disc pl-5 space-y-1">
          <li>Before signing out: EMS accepts it, with <code>auth_source</code> <code>bearer</code> and <code>session_bound</code> <code>true</code>.</li>
          <li>After signing out, the old token: EMS is refused. Porth's authorizer ends a handed-out token with its session (<code>session_ended</code>).</li>
          <li>The IdP may still accept it until its own <code>exp</code>: an access token is a signed JWT, and sign-out revokes the session's refresh token, not the access token.</li>
          <li>A refusal from the gateway may show as "no readable answer". The curl command shows the status, and the authorizer log has the reason; note the time shown.</li>
        </ul>
      </section>
    </div>
  )
}
