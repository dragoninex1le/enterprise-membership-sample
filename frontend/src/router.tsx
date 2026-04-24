import { createBrowserRouter, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import { useHasRole } from './hooks/useRoles'
import { PLATFORM_ADMIN } from './constants'

function RootRedirect() {
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  return isPlatformAdmin
    ? <Navigate to="/admin/platform/tenants" replace />
    : <Navigate to="/dashboard" replace />
}

import DashboardPage from './pages/DashboardPage'
import ARPage from './pages/ARPage'
import APPage from './pages/APPage'
import ApprovalsPage from './pages/ApprovalsPage'
import UnauthorizedPage from './pages/UnauthorizedPage'
import OrganizationsPage from './pages/OrganizationsPage'
import TenantsPage from './pages/TenantsPage'
import ClaimMappingConfigPage from './pages/ClaimMappingConfigPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <RootRedirect /> },

      // ── Functional areas ─────────────────────────────────────────────────────
      {
        element: <ProtectedRoute roles={['viewer', 'ar_clerk', 'ap_clerk', 'controller', PLATFORM_ADMIN]} />,
        children: [{ path: 'dashboard', element: <DashboardPage /> }],
      },
      {
        element: <ProtectedRoute roles={['ar_clerk', 'controller', PLATFORM_ADMIN]} />,
        children: [{ path: 'ar', element: <ARPage /> }],
      },
      {
        element: <ProtectedRoute roles={['ap_clerk', 'controller', PLATFORM_ADMIN]} />,
        children: [{ path: 'ap', element: <APPage /> }],
      },
      {
        element: <ProtectedRoute roles={['controller', PLATFORM_ADMIN]} />,
        children: [{ path: 'approvals', element: <ApprovalsPage /> }],
      },

      // ── Platform admin ─────────────────────────────────────────────────────────
      {
        path: 'admin/platform',
        element: <ProtectedRoute roles={[PLATFORM_ADMIN]} />,
        children: [
          { index: true, element: <Navigate to="tenants" replace /> },
          { path: 'tenants', element: <TenantsPage /> },
          // legacy redirect
          { path: 'organizations', element: <OrganizationsPage /> },
          { path: 'organizations/:orgId/tenants', element: <Navigate to="/admin/platform/tenants" replace /> },
        ],
      },

      // ── Tenant admin ──────────────────────────────────────────────────────────
      {
        path: 'admin/tenant',
        element: <ProtectedRoute roles={[PLATFORM_ADMIN]} />,
        children: [
          { index: true, element: <Navigate to="claim-config" replace /> },
          { path: 'claim-config', element: <ClaimMappingConfigPage /> },
          { path: 'claim-mappings', element: <Navigate to="claim-config" replace /> },
        ],
      },
    ],
  },
  { path: '/unauthorized', element: <UnauthorizedPage /> },
])
