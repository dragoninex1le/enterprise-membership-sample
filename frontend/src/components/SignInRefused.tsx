// PORTH-654 — the question shown when the identity provider refused a sign-in.
// Same frame as pages/UnauthorizedPage.tsx. Rendered instead of the app, so nothing
// starts another sign-in on its own: the provider would refuse again.
import { useState } from 'react'
import { signOutThroughPorth, type SignInRefusal } from '../lib/signInRefusal'

export default function SignInRefused({ refusal }: { refusal: SignInRefusal }) {
  const [stayed, setStayed] = useState(false)

  return (
    <div className="flex h-screen items-center justify-center bg-gray-50 p-6">
      <div className="w-full max-w-lg text-center" role={stayed ? 'alert' : 'dialog'} aria-labelledby="sign-in-refused-title">
        <h1 id="sign-in-refused-title" className="text-lg font-semibold text-gray-900 mb-1">
          {stayed ? 'Sign-in was refused' : "You're signed in with another account"}
        </h1>
        <p className="text-sm text-gray-500 mb-4">
          {stayed
            ? 'You are still signed in with the account that was refused, so signing in again would be refused too.'
            : "This account can't use this console. Sign out and sign in as someone else?"}
        </p>

        {/* The identity provider's own words. Text only — never markup. */}
        {refusal.description && (
          <p data-testid="sign-in-refused-description"
             className="mb-6 rounded-lg border border-gray-200 bg-white p-3 text-left text-xs font-mono text-gray-700 break-words">
            {refusal.description}
          </p>
        )}

        {!stayed && (
          <div className="flex justify-center gap-3">
            <button
              onClick={() => signOutThroughPorth()}
              className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 transition-colors"
            >
              Sign out and use another account
            </button>
            <button
              onClick={() => setStayed(true)}
              className="px-4 py-2 border border-gray-300 text-gray-700 text-sm rounded-lg hover:bg-gray-100 transition-colors"
            >
              Stay signed in
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
