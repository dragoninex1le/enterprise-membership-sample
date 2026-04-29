import axios from 'axios'

export const sampleApiClient = axios.create({
  baseURL: import.meta.env.VITE_SAMPLE_APP_API_URL ?? import.meta.env.VITE_API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

let _getToken: (() => Promise<string>) | null = null

export function setSampleTokenProvider(fn: () => Promise<string>) {
  _getToken = fn
}

sampleApiClient.interceptors.request.use(async (config) => {
  if (_getToken) {
    const token = await _getToken()
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

sampleApiClient.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err.response?.data?.detail ?? err.response?.data?.message ?? err.message
    return Promise.reject(new Error(Array.isArray(detail) ? detail[0]?.msg : detail))
  },
)
