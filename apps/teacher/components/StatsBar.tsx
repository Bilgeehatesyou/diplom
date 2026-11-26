'use client'

interface StudentState {
  id: string
  riskScore: number
  events: { severity: 'low' | 'medium' | 'high'; timestamp: string }[]
  online: boolean
  decision: 'pending' | 'flagged' | 'cleared'
}

interface Props {
  students: StudentState[]
}

function StatCard({
  label, value, sub, accent, icon,
}: {
  label: string
  value: string | number
  sub?: string
  accent: 'blue' | 'emerald' | 'amber' | 'red' | 'slate'
  icon: React.ReactNode
}) {
  const ring = {
    blue: 'from-ufe-500/15 to-ufe-500/0',
    emerald: 'from-emerald-500/15 to-emerald-500/0',
    amber: 'from-amber-500/15 to-amber-500/0',
    red: 'from-red-500/15 to-red-500/0',
    slate: 'from-slate-500/10 to-slate-500/0',
  }[accent]
  const iconColor = {
    blue: 'text-ufe-600 bg-ufe-50 dark:text-ufe-400 dark:bg-ufe-900/40',
    emerald: 'text-emerald-600 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-900/40',
    amber: 'text-amber-600 bg-amber-50 dark:text-amber-400 dark:bg-amber-900/40',
    red: 'text-red-600 bg-red-50 dark:text-red-400 dark:bg-red-900/40',
    slate: 'text-slate-600 bg-slate-100 dark:text-slate-400 dark:bg-slate-800',
  }[accent]

  return (
    <div className="relative overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 transition-all hover:shadow-md hover:-translate-y-0.5">
      <div className={`absolute inset-0 bg-gradient-to-br ${ring} pointer-events-none`} />
      <div className="relative flex items-start justify-between">
        <div className="min-w-0">
          <p className="ufe-caps text-[10px] text-slate-500 dark:text-slate-500">{label}</p>
          <p className="mt-1.5 text-2xl font-bold text-slate-900 dark:text-slate-100 tabular-nums leading-none">{value}</p>
          {sub && <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">{sub}</p>}
        </div>
        <div className={`flex items-center justify-center w-9 h-9 rounded-lg ${iconColor}`}>
          {icon}
        </div>
      </div>
    </div>
  )
}

export default function StatsBar({ students }: Props) {
  const total = students.length
  const online = students.filter(s => s.online).length
  const highRisk = students.filter(s => s.riskScore >= 60).length
  const flagged = students.filter(s => s.decision === 'flagged').length
  const last10m = Date.now() - 10 * 60 * 1000
  const recentEvents = students.reduce(
    (acc, s) => acc + s.events.filter(e => new Date(e.timestamp).getTime() >= last10m).length,
    0
  )
  const avgRisk =
    total > 0
      ? Math.round(students.reduce((a, s) => a + s.riskScore, 0) / total)
      : 0

  return (
    <div className="grid grid-cols-2 gap-3 px-6 py-4 md:grid-cols-5 bg-slate-50 dark:bg-slate-950 border-b border-slate-200 dark:border-slate-800">
      <StatCard
        label="Нийт оюутан"
        value={total}
        sub={`${online} идэвхтэй`}
        accent="blue"
        icon={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
        }
      />
      <StatCard
        label="Идэвхтэй"
        value={online}
        sub={total > 0 ? `${Math.round((online / total) * 100)}%` : '—'}
        accent="emerald"
        icon={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <polyline points="9 12 11 14 15 10" />
          </svg>
        }
      />
      <StatCard
        label="Өндөр эрсдэл"
        value={highRisk}
        sub={highRisk > 0 ? 'Анхаарал татна' : 'Хэвийн'}
        accent={highRisk > 0 ? 'red' : 'slate'}
        icon={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
        }
      />
      <StatCard
        label="Сүүлийн 10 мин"
        value={recentEvents}
        sub="бүртгэгдсэн үйлдэл"
        accent="amber"
        icon={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        }
      />
      <StatCard
        label="Дундаж оноо"
        value={avgRisk}
        sub={flagged > 0 ? `${flagged} тэмдэглэгдсэн` : 'Бүхэлдээ хэвийн'}
        accent={avgRisk >= 60 ? 'red' : avgRisk >= 30 ? 'amber' : 'slate'}
        icon={
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 3v18h18" />
            <path d="M7 14l4-4 4 4 6-6" />
          </svg>
        }
      />
    </div>
  )
}
