'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function StudentLogin() {
  const router = useRouter()
  const [studentId, setStudentId] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/api/login/student`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_id: studentId.trim(), password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Нэвтрэх амжилтгүй')
      }
      const data = await res.json()
      // Fresh login → wipe stale per-student state from any previous exam
      for (const key of Object.keys(localStorage)) {
        if (key.startsWith('ap_answers_') || key.startsWith('ap_endtime_')) {
          localStorage.removeItem(key)
        }
      }
      localStorage.setItem('ap_student', JSON.stringify(data))
      router.push('/')
    } catch (err: any) {
      setError(err.message || 'Алдаа гарлаа')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-100 flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 bg-blue-600 rounded-lg mb-4">
            <span className="text-white text-lg font-bold tracking-tight">AP</span>
          </div>
          <h1 className="text-lg font-semibold text-slate-800">AI Proctor</h1>
          <p className="text-sm text-slate-500 mt-1">Оюутны нэвтрэх хэсэг</p>
        </div>

        <form onSubmit={handleLogin} className="bg-white rounded-lg border border-slate-200 shadow-sm p-6">
          <h2 className="text-base font-semibold text-slate-800 mb-1">Нэвтрэх</h2>
          <p className="text-xs text-slate-500 mb-5">Оюутны кодоо оруулна уу</p>

          <label className="block mb-4">
            <span className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Оюутны код</span>
            <input
              type="text"
              required
              autoFocus
              value={studentId}
              onChange={e => setStudentId(e.target.value.toUpperCase())}
              placeholder="B22FA1260"
              className="mt-1.5 w-full px-3 py-2 text-sm border border-slate-200 rounded-md focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
          </label>

          <label className="block mb-5">
            <span className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Нууц үг</span>
            <input
              type="password"
              required
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="mt-1.5 w-full px-3 py-2 text-sm border border-slate-200 rounded-md focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
          </label>

          {error && (
            <div className="mb-4 text-xs text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !studentId || !password}
            className="w-full py-2.5 text-sm font-semibold rounded-md text-white bg-blue-600 hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400"
          >
            {loading ? 'Нэвтэрч байна...' : 'Нэвтрэх'}
          </button>
        </form>

        <p className="text-center text-xs text-slate-400 mt-6">СЭЗИС · Мэдээллийн систем · 2026</p>
      </div>
    </div>
  )
}
