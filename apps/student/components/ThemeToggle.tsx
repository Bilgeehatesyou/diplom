'use client'
import { useEffect, useState } from 'react'

type Theme = 'light' | 'dark'

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>('light')

  useEffect(() => {
    const stored = (typeof window !== 'undefined' ? localStorage.getItem('ap_theme') : null) as Theme | null
    const next: Theme = stored ?? 'light'
    apply(next)
    setThemeState(next)
  }, [])

  const setTheme = (t: Theme) => {
    apply(t)
    setThemeState(t)
    try { localStorage.setItem('ap_theme', t) } catch {}
  }

  return [theme, setTheme]
}

function apply(t: Theme) {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('dark', t === 'dark')
}

export default function ThemeToggle({ className = '' }: { className?: string }) {
  const [theme, setTheme] = useTheme()
  const isDark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      aria-label="Theme toggle"
      title={isDark ? 'Цайвар горим' : 'Бараан горим'}
      className={`relative inline-flex items-center h-6 w-11 rounded-full transition-colors duration-200
        ${isDark ? 'bg-ufe-700' : 'bg-slate-300'} ${className}`}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow-sm flex items-center justify-center
          transition-transform duration-200 ${isDark ? 'translate-x-5' : 'translate-x-0'}`}
      >
        {isDark ? (
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#1543a1" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        ) : (
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
          </svg>
        )}
      </span>
    </button>
  )
}
