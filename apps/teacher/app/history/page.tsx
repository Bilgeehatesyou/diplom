'use client'
import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import ThemeToggle from '../../components/ThemeToggle'
import AuthImage from '../../components/AuthImage'
import { apiFetch, downloadFile, getTeacher, TeacherAuth } from '../../lib/api'

interface HistorySession {
  session_id: number
  student_id: string
  student_name: string
  department: string
  exam_id: string
  risk_score: number
  decision: string
  started_at: string | null
  ended_at: string | null
  event_count: number
}

interface RiskEv {
  event_type: string
  severity: 'low' | 'medium' | 'high'
  timestamp: string
  message: string
  confidence?: number
  snapshot?: string | null
}

interface SessionDetail {
  session_id: number
  student_id: string
  risk_score: number
  decision: string
  started_at: string | null
  ended_at: string | null
  events: RiskEv[]
}

// exam_id → friendly course name (хичээлийн нэрсийг энд бичиж тохируулна)
const COURSE_NAMES: Record<string, string> = {
  exam_001: 'Мэдээллийн систем',
}

function formatDateTime(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('mn-MN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

function formatDate(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('mn-MN', {
    year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'long',
  })
}

function dateKey(iso: string | null) {
  if (!iso) return 'unknown'
  return new Date(iso).toISOString().slice(0, 10) // YYYY-MM-DD
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('mn-MN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function riskColor(score: number) {
  if (score >= 60) return 'text-red-600 dark:text-red-400'
  if (score >= 30) return 'text-amber-600 dark:text-amber-400'
  return 'text-emerald-600 dark:text-emerald-400'
}

function decisionBadge(decision: string) {
  switch (decision) {
    case 'flagged':  return { label: 'Сэжигтэй',    cls: 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 border-red-200 dark:border-red-900/40' }
    case 'cleared':  return { label: 'Зөрчилгүй',    cls: 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900/40' }
    case 'reset':    return { label: 'Цэвэрлэгдсэн', cls: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700' }
    case 'archived': return { label: 'Архивласан',   cls: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700' }
    case 'pending':  return { label: 'Шийдвэргүй',   cls: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700' }
    default:         return { label: decision,       cls: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700' }
  }
}

export default function HistoryPage() {
  const router = useRouter()
  const [teacher, setTeacher] = useState<TeacherAuth | null>(null)
  const [sessions, setSessions] = useState<HistorySession[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterCourse, setFilterCourse] = useState<string>('all')
  const [snapshotPreview, setSnapshotPreview] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  useEffect(() => {
    const t = getTeacher()
    if (!t) { router.push('/login'); return }
    setTeacher(t)
  }, [router])

  useEffect(() => {
    if (!teacher) return
    apiFetch<HistorySession[]>('/api/history')
      .then((rows: HistorySession[]) => {
        setSessions(rows)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [teacher])

  useEffect(() => {
    if (selectedId === null) { setDetail(null); return }
    apiFetch<SessionDetail>(`/api/history/session/${selectedId}`)
      .then(setDetail)
      .catch(() => setDetail(null))
  }, [selectedId])

  // Filter by search + course
  const filtered = useMemo(() => sessions.filter(s => {
    if (filterCourse !== 'all' && s.exam_id !== filterCourse) return false
    if (!search.trim()) return true
    const q = search.trim().toLowerCase()
    return s.student_name.toLowerCase().includes(q) ||
           s.student_id.toLowerCase().includes(q)
  }), [sessions, search, filterCourse])

  // Group: Course → Date → Sessions
  const tree = useMemo(() => {
    const byCourse: Record<string, Record<string, HistorySession[]>> = {}
    for (const s of filtered) {
      const c = s.exam_id || 'unknown'
      const d = dateKey(s.started_at)
      if (!byCourse[c]) byCourse[c] = {}
      if (!byCourse[c][d]) byCourse[c][d] = []
      byCourse[c][d].push(s)
    }
    return byCourse
  }, [filtered])

  const courses = useMemo(() => {
    const set = new Set<string>()
    sessions.forEach(s => set.add(s.exam_id || 'unknown'))
    return Array.from(set)
  }, [sessions])

  const toggleExpand = (key: string) => {
    setExpanded(p => ({ ...p, [key]: !p[key] }))
  }

  if (!teacher) return null

  return (
    <div className="flex flex-col min-h-screen bg-slate-50 dark:bg-slate-950">
      <header className="flex items-center justify-between px-6 py-3 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-9 h-9 rounded-lg bg-gradient-to-br from-ufe-600 to-ufe-700 shadow-md shadow-ufe-500/30">
            <span className="text-sm font-bold text-white tracking-tight">AP</span>
          </div>
          <div>
            <h1 className="ufe-caps text-xs text-slate-900 dark:text-slate-100">Шалгалтын түүх</h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Архивласан шалгалтуудын мэдээлэл · {teacher.name}</p>
          </div>
        </div>

        <div className="flex items-center gap-5">
          <ThemeToggle />
          <button
            onClick={() => router.push('/')}
            className="ufe-caps text-xs text-slate-700 dark:text-slate-300 hover:text-ufe-600 dark:hover:text-ufe-400 transition-colors"
          >
            ← Үндсэн самбар
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="flex flex-col w-96 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800">
          <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 space-y-2">
            <div className="flex items-center justify-between">
              <span className="ufe-caps text-[10px] text-slate-500 dark:text-slate-400">
                Нийт түүх
              </span>
              <span className="text-xs bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-0.5 rounded-md font-medium tabular-nums">
                {filtered.length}
              </span>
            </div>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Оюутны нэр / кодоор хайх..."
              className="w-full px-3 py-1.5 text-xs rounded-md bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:border-ufe-500 focus:ring-1 focus:ring-ufe-500"
            />
            <select
              value={filterCourse}
              onChange={e => setFilterCourse(e.target.value)}
              className="w-full px-3 py-1.5 text-xs rounded-md bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:border-ufe-500 focus:ring-1 focus:ring-ufe-500"
            >
              <option value="all">Бүх хичээл</option>
              {courses.map(c => (
                <option key={c} value={c}>{COURSE_NAMES[c] || c}</option>
              ))}
            </select>
          </div>

          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center py-16">
                <div className="w-6 h-6 border-2 border-slate-300 dark:border-slate-700 border-t-ufe-500 rounded-full animate-spin" />
              </div>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center px-4 py-16 text-center">
                <div className="flex items-center justify-center w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800 mb-3">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-slate-400 dark:text-slate-500">
                    <path d="M21 8v13H3V8" /><path d="M1 3h22v5H1z" /><path d="M10 12h4" />
                  </svg>
                </div>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-300">Түүх хоосон байна</p>
                <p className="text-xs text-slate-500 mt-1">Дашбоард дээр "Архивлах" товч дарна уу</p>
              </div>
            ) : (
              <div>
                {Object.keys(tree).sort().map(courseId => {
                  const courseKey = `c:${courseId}`
                  const courseExpanded = expanded[courseKey] !== false // default open
                  const dates = Object.keys(tree[courseId]).sort().reverse() // latest first
                  const totalInCourse = dates.reduce((a, d) => a + tree[courseId][d].length, 0)
                  return (
                    <div key={courseId} className="border-b border-slate-100 dark:border-slate-800">
                      {/* Course header */}
                      <button
                        onClick={() => toggleExpand(courseKey)}
                        className="w-full flex items-center justify-between px-3 py-2.5 bg-slate-50 dark:bg-slate-950/50 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <svg
                            width="10" height="10" viewBox="0 0 24 24" fill="none"
                            stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"
                            className={`text-slate-500 transition-transform ${courseExpanded ? 'rotate-90' : ''}`}
                          >
                            <polyline points="9 18 15 12 9 6" />
                          </svg>
                          <span className="ufe-caps text-[11px] text-ufe-700 dark:text-ufe-400">
                            {COURSE_NAMES[courseId] || courseId}
                          </span>
                        </div>
                        <span className="text-[10px] tabular-nums text-slate-500">{totalInCourse}</span>
                      </button>

                      {courseExpanded && dates.map(date => {
                        const dateKey = `d:${courseId}:${date}`
                        const dateExpanded = expanded[dateKey] !== false
                        const list = tree[courseId][date]
                        return (
                          <div key={date}>
                            {/* Date header */}
                            <button
                              onClick={() => toggleExpand(dateKey)}
                              className="w-full flex items-center justify-between pl-7 pr-3 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                            >
                              <div className="flex items-center gap-2">
                                <svg
                                  width="9" height="9" viewBox="0 0 24 24" fill="none"
                                  stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"
                                  className={`text-slate-400 transition-transform ${dateExpanded ? 'rotate-90' : ''}`}
                                >
                                  <polyline points="9 18 15 12 9 6" />
                                </svg>
                                <span className="text-[11px] tabular-nums text-slate-600 dark:text-slate-300">
                                  {formatDate(list[0].started_at)}
                                </span>
                              </div>
                              <span className="text-[10px] tabular-nums text-slate-500">{list.length}</span>
                            </button>

                            {dateExpanded && list.map(s => {
                              const badge = decisionBadge(s.decision)
                              const isSelected = selectedId === s.session_id
                              return (
                                <div
                                  key={s.session_id}
                                  onClick={() => setSelectedId(s.session_id)}
                                  className={`pl-10 pr-3 py-2.5 cursor-pointer border-l-2 transition-all ${
                                    isSelected
                                      ? 'bg-ufe-50 dark:bg-ufe-900/30 border-l-ufe-500'
                                      : 'border-l-transparent hover:bg-slate-50 dark:hover:bg-slate-800/50'
                                  }`}
                                >
                                  <div className="flex items-center justify-between mb-1">
                                    <div className="text-sm font-medium truncate text-slate-900 dark:text-slate-100">{s.student_name}</div>
                                    <span className={`text-sm font-bold tabular-nums ${riskColor(s.risk_score)}`}>
                                      {Math.round(s.risk_score)}
                                    </span>
                                  </div>
                                  <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400">
                                    <span className="tabular-nums">{s.student_id}</span>
                                    <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium border ${badge.cls}`}>
                                      {badge.label}
                                    </span>
                                  </div>
                                  <div className="text-[10px] tabular-nums text-slate-400 dark:text-slate-500 mt-0.5">
                                    {formatDateTime(s.started_at)} · {s.event_count} үйлдэл
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </aside>

        <main className="flex-1 p-6 overflow-y-auto bg-grid-subtle">
          {!detail ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-ufe-500/10 to-ufe-600/10 mb-4">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-ufe-600 dark:text-ufe-400">
                  <path d="M21 8v13H3V8" /><path d="M1 3h22v5H1z" /><path d="M10 12h4" />
                </svg>
              </div>
              <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">Session сонгогдоогүй</p>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Зүүн талын жагсаалтаас session сонгож харна уу</p>
            </div>
          ) : (
            <div className="flex flex-col max-w-5xl gap-5 mx-auto animate-fade-up">
              <div className="p-5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">{detail.student_id}</h2>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                      Session #{detail.session_id}
                    </p>
                  </div>
                  <div className="text-right">
                    <div className={`text-3xl font-bold ${riskColor(detail.risk_score)}`}>
                      {Math.round(detail.risk_score)}
                    </div>
                    <div className="ufe-caps text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">Эрсдэлийн оноо</div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="px-3 py-2 bg-slate-50 dark:bg-slate-950 rounded-md border border-slate-200 dark:border-slate-800">
                    <div className="ufe-caps text-[9px] text-slate-500 dark:text-slate-400 mb-1">Эхэлсэн</div>
                    <div className="text-slate-800 dark:text-slate-200 tabular-nums">{formatDateTime(detail.started_at)}</div>
                  </div>
                  <div className="px-3 py-2 bg-slate-50 dark:bg-slate-950 rounded-md border border-slate-200 dark:border-slate-800">
                    <div className="ufe-caps text-[9px] text-slate-500 dark:text-slate-400 mb-1">Дууссан</div>
                    <div className="text-slate-800 dark:text-slate-200 tabular-nums">{formatDateTime(detail.ended_at)}</div>
                  </div>
                </div>
              </div>

              <div className="overflow-hidden bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm">
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-800">
                  <h3 className="ufe-caps text-xs text-slate-800 dark:text-slate-200">Бүртгэгдсэн үйлдлүүд</h3>
                  <div className="flex items-center gap-3">
                    <span className="text-xs bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-0.5 rounded-md font-medium tabular-nums">
                      {detail.events.length}
                    </span>
                    <button
                      onClick={() => downloadFile(`/api/report/student/${detail.student_id}.csv?session_id=${detail.session_id}`,
                                                  `report_${detail.student_id}_s${detail.session_id}.csv`)
                                        .catch(() => alert('Тайлан татахад алдаа гарлаа'))}
                      className="ufe-caps text-[10px] text-ufe-600 dark:text-ufe-400 hover:text-ufe-700 dark:hover:text-ufe-300 transition-colors"
                    >
                      Тайлан татах
                    </button>
                  </div>
                </div>

                {detail.events.length === 0 ? (
                  <div className="py-12 text-sm text-center text-slate-500 dark:text-slate-400">
                    Үйлдэл бүртгэгдээгүй
                  </div>
                ) : (
                  <div className="divide-y divide-slate-200 dark:divide-slate-800">
                    {detail.events.map((ev, i) => (
                      <div key={i} className="flex items-start gap-3 px-5 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                        <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 mt-[5px] ${
                          ev.severity === 'high' ? 'bg-red-500' : ev.severity === 'medium' ? 'bg-amber-500' : 'bg-blue-500'
                        }`} />
                        {ev.snapshot ? (
                          <AuthImage
                            snapshot={ev.snapshot}
                            onOpen={setSnapshotPreview}
                            className="flex-shrink-0 object-cover w-16 h-12 border rounded cursor-pointer border-slate-200 dark:border-slate-700 hover:border-ufe-500"
                          />
                        ) : (
                          <div className="flex-shrink-0 w-16 h-12 rounded bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800" />
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-slate-800 dark:text-slate-200">{ev.message}</p>
                          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{formatTime(ev.timestamp)}</p>
                        </div>
                        <span className={`flex-shrink-0 text-[10px] px-2 py-1 rounded-md font-semibold uppercase tracking-wider ${
                          ev.severity === 'high' ? 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300' :
                          ev.severity === 'medium' ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300' : 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'
                        }`}>
                          {ev.severity === 'high' ? 'Өндөр' : ev.severity === 'medium' ? 'Дунд' : 'Бага'}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </main>
      </div>

      {snapshotPreview && (
        <div
          onClick={() => setSnapshotPreview(null)}
          className="fixed inset-0 z-50 flex items-center justify-center p-8 cursor-pointer bg-black/85 backdrop-blur-sm"
        >
          <img src={snapshotPreview} alt="snapshot" className="object-contain max-w-full max-h-full rounded-lg shadow-2xl" />
        </div>
      )}
    </div>
  )
}
