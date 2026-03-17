import { Outlet } from 'react-router-dom'
import { useAuth0 } from '@auth0/auth0-react'
import Sidebar from './Sidebar'

export default function Layout() {
  const { isAuthenticated, loginWithRedirect, logout, user } = useAuth0()

  if (!isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Porth Admin</h1>
          <p className="text-gray-500 mb-6">Enterprise membership management</p>
          <button
            onClick={() => loginWithRedirect()}
            className="px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-medium"
          >
            Sign in
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
          <span className="text-sm text-gray-400">Porth Admin</span>
          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-700">{user?.email}</span>
            <button
              onClick={() => logout({ logoutParams: { returnTo: window.location.origin } })}
              className="text-sm text-gray-400 hover:text-gray-700 transition-colors"
            >
              Sign out
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
