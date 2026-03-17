// PORTH-129 — Build User management screen
import { useParams } from 'react-router-dom'
export default function UsersPage() {
  const { orgId, tenantId } = useParams()
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Users</h1>
      <p className="text-gray-400 text-sm">Tenant: {tenantId} &mdash; implementation pending (PORTH-129)</p>
    </div>
  )
}
