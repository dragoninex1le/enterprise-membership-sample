import axios, { type InternalAxiosRequestConfig } from 'axios'
import { applyCookieAuth } from './client'
import { onAuthError } from '../lib/sessionExpiry'

// Sample-app API client. Same cookie/BFF contract as the Porth client
// (PORTH-531): the browser holds no token, the http-only session cookie
// authenticates, and mutating requests carry the session CSRF secret.
export const sampleApiClient = axios.create({
  baseURL: import.meta.env.VITE_SAMPLE_APP_API_URL ?? import.meta.env.VITE_API_BASE_URL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

sampleApiClient.interceptors.request.use((config: InternalAxiosRequestConfig) =>
  applyCookieAuth(config),
)

sampleApiClient.interceptors.response.use(
  (res) => res,
  (err) => {
    // Same dead-session recovery as the Porth client — the two must not drift.
    void onAuthError(err).catch(() => undefined)
    const detail = err.response?.data?.detail ?? err.response?.data?.message ?? err.message
    return Promise.reject(new Error(Array.isArray(detail) ? detail[0]?.msg : detail))
  },
)
