export const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
export const WS = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'

export interface StudentAuth {
  student_id: string
  name: string
  department: string
  token: string
}

const KEY = 'ap_student'

export function getStudent(): StudentAuth | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const s = JSON.parse(raw)
    return s && s.token ? (s as StudentAuth) : null   // хуучин (token-гүй) бүртгэл → дахин нэвтрэх
  } catch {
    return null
  }
}

export function setStudent(s: StudentAuth) {
  localStorage.setItem(KEY, JSON.stringify(s))
}

export function clearStudent() {
  localStorage.removeItem(KEY)
}

export class ApiError extends Error {
  status: number
  code?: string
  constructor(status: number, message: string, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

/** Authorization header-тэй fetch. 401 → нэвтрэлт хүчингүй. */
export async function apiFetch<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const s = getStudent()
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> || {}) }
  if (s) headers['Authorization'] = `Bearer ${s.token}`
  if (init.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json'
  const res = await fetch(`${API}${path}`, { ...init, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const d = body?.detail
    const message = typeof d === 'string' ? d : d?.message || 'Алдаа гарлаа'
    throw new ApiError(res.status, message, typeof d === 'object' ? d?.code : undefined)
  }
  return res.json()
}
