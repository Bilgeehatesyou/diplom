export const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
export const WS = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'

export interface TeacherAuth {
  teacher_id: number
  name: string
  token: string
}

const KEY = 'ap_teacher'

export function getTeacher(): TeacherAuth | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const t = JSON.parse(raw)
    return t && t.token ? (t as TeacherAuth) : null   // хуучин (token-гүй) бүртгэл → дахин нэвтрэх
  } catch {
    return null
  }
}

export function setTeacher(t: TeacherAuth) {
  localStorage.setItem(KEY, JSON.stringify(t))
}

export function clearTeacher() {
  localStorage.removeItem(KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function authHeaders(extra?: HeadersInit): Record<string, string> {
  const headers: Record<string, string> = { ...(extra as Record<string, string> || {}) }
  const t = getTeacher()
  if (t) headers['Authorization'] = `Bearer ${t.token}`
  return headers
}

/** Authorization header-тэй fetch. 401 үед нэвтрэх хуудас руу шилжинэ. */
export async function apiFetch<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, { ...init, headers: authHeaders(init.headers) })
  if (res.status === 401) {
    clearTeacher()
    if (typeof window !== 'undefined') window.location.href = '/login'
    throw new ApiError(401, 'Нэвтрэх шаардлагатай')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const d = body?.detail
    throw new ApiError(res.status, typeof d === 'string' ? d : d?.message || 'Алдаа гарлаа')
  }
  return res.json()
}

/** Хамгаалагдсан файлыг (зураг, CSV) blob-оор татна. */
export async function apiBlob(path: string): Promise<Blob> {
  const res = await fetch(`${API}${path}`, { headers: authHeaders() })
  if (!res.ok) throw new ApiError(res.status, 'Файл татаж чадсангүй')
  return res.blob()
}

export async function downloadFile(path: string, filename: string) {
  const blob = await apiBlob(path)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}
