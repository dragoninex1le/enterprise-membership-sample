import axios from 'axios'

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

let _getToken: (() => Promise<string>) | null = null

export function setTokenProvider(fn: () => Promise<string>) {
  _getToken = fn
}

apiClient.interceptors.request.use(async (config) => {
  if (_getToken) {
    const token = await _getToken()
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err.response?.data?.detail ?? err.response?.data?.message ?? err.message
    return Promise.reject(new Error(Array.isArray(detail) ? detail[0]?.msg : detail))
  },
)
