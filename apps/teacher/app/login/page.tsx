'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import ThemeToggle from '../../components/ThemeToggle'
import { API, setTeacher } from '../../lib/api'

export default function TeacherLogin() {
  const router = useRouter()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/api/login/teacher`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Нэвтрэх амжилтгүй')
      }
      const data = await res.json()
      setTeacher(data)
      router.push('/')
    } catch (err: any) {
      setError(err.message || 'Алдаа гарлаа')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center p-6">
      <div className="absolute top-6 right-6">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 bg-gradient-to-br from-ufe-600 to-ufe-700 rounded-lg mb-4 shadow-md shadow-ufe-500/30">
            <span className="text-white text-lg font-bold tracking-tight">AP</span>
          </div>
          <h1 className="ufe-caps text-base text-slate-900 dark:text-slate-100">AI Proctor</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">Багшийн нэвтрэх хэсэг</p>
        </div>

        <form onSubmit={handleLogin} className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 shadow-sm p-6">
          <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100 mb-1">Нэвтрэх</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-5">Багшийн нэр болон нууц үгээ оруулна уу</p>

          <label className="block mb-4">
            <span className="ufe-caps text-[10px] text-slate-600 dark:text-slate-300">Багшийн нэр</span>
            <input
              type="text"
              required
              autoFocus
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Tsetsegee"
              className="mt-1.5 w-full px-3 py-2 text-sm bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 rounded-md focus:outline-none focus:border-ufe-500 focus:ring-1 focus:ring-ufe-500 placeholder-slate-400 dark:placeholder-slate-600"
            />
          </label>

          <label className="block mb-5">
            <span className="ufe-caps text-[10px] text-slate-600 dark:text-slate-300">Нууц үг</span>
            <input
              type="password"
              required
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="mt-1.5 w-full px-3 py-2 text-sm bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 rounded-md focus:outline-none focus:border-ufe-500 focus:ring-1 focus:ring-ufe-500"
            />
          </label>

          {error && (
            <div className="mb-4 text-xs text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 rounded-md px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !name || !password}
            className="ufe-caps w-full py-2.5 text-sm rounded-md text-white bg-ufe-600 hover:bg-ufe-700 disabled:bg-slate-200 dark:disabled:bg-slate-800 disabled:text-slate-400 dark:disabled:text-slate-500"
          >
            {loading ? 'Нэвтэрч байна...' : 'Нэвтрэх'}
          </button>
        </form>

        <p className="ufe-caps text-center text-[10px] text-slate-400 dark:text-slate-500 mt-6">СЭЗИС · Мэдээллийн систем · 2026</p>
      </div>
    </div>
  )
}
