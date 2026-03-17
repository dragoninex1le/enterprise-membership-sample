import { useAuth0 } from '@auth0/auth0-react'
import { RouterProvider } from 'react-router-dom'
import { useEffect } from 'react'
import { router } from './router'
import { setTokenProvider } from './api/client'

export default function App() {
  const { isLoading, error, isAuthenticated, getAccessTokenSilently } = useAuth0()

  // Wire Auth0 token into the API client
  useEffect(() => {
    if (isAuthenticated) {
      setTokenProvider(getAccessTokenSilently)
    }
  }, [isAuthenticated, getAccessTokenSilently])

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-gray-500 text-sm">Loading…</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-red-600 text-sm">Auth error: {error.message}</div>
      </div>
    )
  }

  return <RouterProvider router={router} />
}
