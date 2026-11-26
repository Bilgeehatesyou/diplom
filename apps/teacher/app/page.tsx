'use client'
import { useEffect, useState, useRef } from 'react'
import { useRouter } from 'next/navigation'
import RiskGauge from '../components/RiskGauge'
import Sparkline from '../components/Sparkline'
import StatsBar from '../components/StatsBar'
import ThemeToggle from '../components/ThemeToggle'
import AuthImage from '../components/AuthImage'
import { WS, apiFetch, downloadFile, getTeacher, clearTeacher, TeacherAuth } from '../lib/api'

interface SubmissionView {
  session_id: number
  submitted_at: string | null
  auto_submitted: boolean
  updated_at: string | null
  items: { id: number; text: string; type: string; answer: string }[]
}

interface RiskEv {
  event_type: string
  severity: 'low' | 'medium' | 'high'
  timestamp: string
  message: string
  confidence?: number
  snapshot?: string | null
}

interface DashboardRow {
  id: string
  name: string
  department: string
  session_id: number | null
  risk_score: number
  decision: 'pending' | 'flagged' | 'cleared'
  online: boolean
  active: boolean
  started_at: string | null
  ended_at: string | null
  submitted_at: string | null
  events: RiskEv[]
}

interface StudentState {
  id: string
  name: string
  department: string
  sessionId: number | null
  riskScore: number
  events: RiskEv[]
  decision: 'pending' | 'flagged' | 'cleared'
  online: boolean
  active: boolean
  submittedAt: string | null
}

function rowsToState(rows: DashboardRow[]): Record<string, StudentState> {
  const map: Record<string, StudentState> = {}
  for (const r of rows) {
    map[r.id] = {
      id: r.id, name: r.name, department: r.department, sessionId: r.session_id,
      riskScore: Math.min(100, r.risk_score), events: r.events,
      decision: r.decision, online: r.online, active: r.active, submittedAt: r.submitted_at,
    }
  }
  return map
}

function severityColor(score: number) {
  if (score >= 60) return 'bg-red-500'
  if (score >= 30) return 'bg-amber-500'
  return 'bg-emerald-500'
}
function severityTextColor(score: number) {
  if (score >= 60) return 'text-red-600 dark:text-red-400'
  if (score >= 30) return 'text-amber-600 dark:text-amber-400'
  return 'text-emerald-600 dark:text-emerald-400'
}
function severityBg(score: number) {
  if (score >= 60) return 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900/40'
  if (score >= 30) return 'bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/40'
  return 'bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-900/40'
}
function riskBadge(score: number) {
  if (score >= 60) return 'text-red-700 dark:text-red-300 bg-red-100 dark:bg-red-900/40'
  if (score >= 30) return 'text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-900/40'
  return 'text-emerald-700 dark:text-emerald-300 bg-emerald-100 dark:bg-emerald-900/40'
}
function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('mn-MN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const EVENT_LABEL: Record<string, string> = {
  face_missing: 'Нүүр кадраас гарсан',
  multiple_faces: 'Олон хүн',
  gaze_away: 'Өөр тийш харав',
  looking_down: 'Удаан доош харав',
  looking_down_phone: 'Доош харах + утас',
  object_detected: 'Объект',
  audio_speech: 'Тасралтгүй яриа',
  audio_short_speech: 'Богино яриа',
  audio_whispering: 'Шивнэх',
  audio_talking: 'Ярилцаж байна',
  audio_multiple_voices: 'Олон хүний яриа',
  tab_switch: 'Tab сэлгэв',
  focus_lost: 'Цонхноос гарсан',
  fullscreen_exit: 'Бүтэн дэлгэцээс гарсан',
  copy_attempt: 'Хуулах оролдлого',
  video_stalled: 'Камерын дүрс зогссон',
  audio_stalled: 'Микрофоны дуу зогссон',
  stream_lost: 'Холболт тасарсан',
  mic_denied: 'Микрофон зөвшөөрөөгүй',
  mic_ended: 'Микрофон салсан',
  camera_ended: 'Камер салсан',
  virtual_camera: 'Виртуал камер',
  liveness_failed: 'Камерын даалгавар биелүүлээгүй',
}

function EventIcon({ type }: { type: string }) {
  const cls = 'w-3.5 h-3.5'
  switch (type) {
    case 'face_missing':
    case 'multiple_faces':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
        </svg>
      )
    case 'gaze_away':
    case 'looking_down':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
        </svg>
      )
    case 'object_detected':
    case 'looking_down_phone':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="5" y="2" width="14" height="20" rx="2" /><line x1="12" y1="18" x2="12" y2="18" />
        </svg>
      )
    case 'audio_speech':
    case 'audio_short_speech':
    case 'audio_talking':
    case 'audio_multiple_voices':
    case 'audio_whispering':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><line x1="12" y1="19" x2="12" y2="23" />
        </svg>
      )
    case 'tab_switch':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18" />
        </svg>
      )
    case 'copy_attempt':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )
    default:
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      )
  }
}

export default function TeacherDashboard() {
  const router = useRouter()
  const wsRef = useRef<WebSocket | null>(null)
  const selectedRef = useRef<string | null>(null)
  const videoImgRef = useRef<HTMLImageElement | null>(null)
  const currentBlobUrlRef = useRef<string | null>(null)
  const studentsRef = useRef<Record<string, StudentState>>({})
  const [teacher, setTeacher] = useState<TeacherAuth | null>(null)
  const [students, setStudents] = useState<Record<string, StudentState>>({})
  const [submission, setSubmission] = useState<SubmissionView | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [criticalAlerts, setCriticalAlerts] = useState<string[]>([])
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')
  const [hasFrame, setHasFrame] = useState(false)
  const [snapshotPreview, setSnapshotPreview] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  useEffect(() => { selectedRef.current = selected }, [selected])
  useEffect(() => { studentsRef.current = students }, [students])
  useEffect(() => { setSubmission(null) }, [selected])

  useEffect(() => {
    const t = getTeacher()
    if (!t) { router.push('/login'); return }
    setTeacher(t)
  }, [router])

  const loadDashboard = async () => {
    const rows = await apiFetch<DashboardRow[]>('/api/dashboard')
    setStudents(rowsToState(rows))
  }

  useEffect(() => {
    if (!teacher) return
    loadDashboard().catch(() => {})
  }, [teacher])

  useEffect(() => {
    if (!teacher) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const connect = () => {
      if (stopped) return
      const ws = new WebSocket(`${WS}/ws/teacher`)
      ws.binaryType = 'blob'
      setConnectionStatus('connecting')

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'auth', token: teacher.token }))   // token URL-д биш
        setConnectionStatus('connected')
        if (selectedRef.current) {
          ws.send(JSON.stringify({ action: 'watch', student_id: selectedRef.current }))
        }
      }
      ws.onclose = (e) => {
        setConnectionStatus('disconnected')
        if (stopped) return
        if (e.code === 4401) { clearTeacher(); router.push('/login'); return }
        timer = setTimeout(connect, 3000)
      }
      ws.onerror = () => setConnectionStatus('disconnected')

      ws.onmessage = (e) => {
        if (e.data instanceof Blob) {
          const url = URL.createObjectURL(e.data)
          if (videoImgRef.current) videoImgRef.current.src = url
          if (currentBlobUrlRef.current) URL.revokeObjectURL(currentBlobUrlRef.current)
          currentBlobUrlRef.current = url
          setHasFrame(true)
          return
        }
        const data = JSON.parse(e.data)
        if (data.ack === 'decide' || data.error) return

        if (data.meta === 'online' || data.meta === 'offline') {
          const sid = data.student_id
          if (data.meta === 'online' && !studentsRef.current[sid]?.active) {
            loadDashboard().catch(() => {})   // шинэ session → бүтэн мэдээллийг дахин авна
            return
          }
          setStudents(prev => {
            if (!prev[sid]) return prev
            return { ...prev, [sid]: { ...prev[sid], online: data.meta === 'online',
                                       ...(data.meta === 'online' ? { active: true } : {}) } }
          })
          return
        }

        // Оноог зөвхөн сервер тооцно (decay мөн серверт) — client давхар тооцохгүй
        if (data.meta === 'scores') {
          setStudents(prev => {
            const next = { ...prev }
            for (const [sid, score] of Object.entries(data.scores as Record<string, number>)) {
              if (next[sid]) next[sid] = { ...next[sid], riskScore: Math.min(100, score) }
            }
            return next
          })
          return
        }

        if (data.meta === 'submitted') {
          setStudents(prev => {
            const s = prev[data.student_id]
            if (!s) return prev
            return { ...prev, [data.student_id]: { ...s, active: false, submittedAt: new Date().toISOString() } }
          })
          return
        }

        const { student_id, event, risk_score } = data
        if (!event) return

        setStudents(prev => {
          const existing = prev[student_id] || {
            id: student_id, name: student_id, department: '—', sessionId: null,
            riskScore: 0, events: [], decision: 'pending' as const, online: true,
            active: true, submittedAt: null,
          }
          return {
            ...prev,
            [student_id]: {
              ...existing,
              riskScore: typeof risk_score === 'number' ? Math.min(100, risk_score) : existing.riskScore,
              events: [event, ...existing.events].slice(0, 100),
            },
          }
        })

        if (event.severity === 'high') {
          const name = studentsRef.current[student_id]?.name || student_id
          const msg = `[${formatTime(event.timestamp)}] ${name}: ${event.message}`
          setCriticalAlerts(p => [msg, ...p].slice(0, 8))
        }
      }

      wsRef.current = ws
    }
    connect()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      wsRef.current?.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teacher])

  useEffect(() => {
    setHasFrame(false)
    if (currentBlobUrlRef.current) {
      URL.revokeObjectURL(currentBlobUrlRef.current)
      currentBlobUrlRef.current = null
    }
    if (videoImgRef.current) videoImgRef.current.removeAttribute('src')

    if (!selected) return
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'watch', student_id: selected }))
    }
    return () => {
      const w = wsRef.current
      if (w?.readyState === WebSocket.OPEN) {
        w.send(JSON.stringify({ action: 'unwatch' }))
      }
    }
  }, [selected])

  const handleDecision = (id: string, d: 'flagged' | 'cleared' | 'pending') => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'decide', student_id: id, decision: d }))
    }
    setStudents(p => {
      const s = p[id]
      if (!s) return p
      return {
        ...p,
        [id]: {
          ...s,
          decision: d,
          riskScore: d === 'cleared' ? 0 : s.riskScore,
        },
      }
    })
  }

  const handleClear = async (id: string) => {
    if (!confirm('Энэ оюутны бүртгэгдсэн үйлдлийг цэвэрлэх үү?\n(Мэдээлэл өгөгдлийн санд хадгалагдсан хэвээр үлдэнэ. Оюутан шалгалтыг дахин өгөх боломжтой болно.)')) return
    try {
      await apiFetch(`/api/session/${id}/clear`, { method: 'POST' })
      setStudents(p => {
        const s = p[id]
        if (!s) return p
        return { ...p, [id]: { ...s, events: [], riskScore: 0, decision: 'pending', sessionId: null, submittedAt: null } }
      })
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Цэвэрлэхэд алдаа гарлаа')
    }
  }

  const handleShowAnswers = async (s: StudentState) => {
    if (!s.sessionId) return
    try {
      setSubmission(await apiFetch<SubmissionView>(`/api/session/${s.sessionId}/submission`))
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Хариулт ачаалахад алдаа гарлаа')
    }
  }

  const handleDownloadCsv = (s: StudentState) => {
    const q = s.sessionId ? `?session_id=${s.sessionId}` : ''
    downloadFile(`/api/report/student/${s.id}.csv${q}`, `report_${s.id}.csv`)
      .catch(() => alert('Тайлан татахад алдаа гарлаа'))
  }

  const handleLogout = async () => {
    // Logout-ийн өмнө бүх дууссан session-уудыг архивлана
    try {
      await apiFetch('/api/dashboard/archive', { method: 'POST' })
    } catch {}
    clearTeacher()
    router.push('/login')
  }

  const handleArchiveAll = async () => {
    if (!confirm('Бүх дууссан шалгалтын мэдээллийг "Шалгалтын түүх" хэсэгт нүүлгэх үү?')) return
    try {
      const data = await apiFetch<{ archived: number }>('/api/dashboard/archive', { method: 'POST' })
      await loadDashboard()
      setSelected(null)
      alert(`${data.archived} session түүх рүү шилжсэн`)
    } catch (e) {
      console.error(e)
      alert('Архивлахад алдаа гарлаа')
    }
  }

  if (!teacher) return null

  const allList = Object.values(students)
  const studentList = allList
    .filter(s => {
      if (!search.trim()) return true
      const q = search.trim().toLowerCase()
      return s.name.toLowerCase().includes(q) || s.id.toLowerCase().includes(q)
    })
    .sort((a, b) => {
      if (a.online !== b.online) return a.online ? -1 : 1
      return b.riskScore - a.riskScore
    })
  const selectedStudent = selected ? students[selected] : null

  return (
    <div className="flex flex-col min-h-screen bg-slate-50 dark:bg-slate-950">
      <header className="flex items-center justify-between px-6 py-3 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-9 h-9 rounded-lg bg-gradient-to-br from-blue-600 to-indigo-700 shadow-md shadow-blue-500/30">
            <span className="text-sm font-bold text-white tracking-tight">AP</span>
            <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-500 border-2 border-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold leading-none text-slate-900 dark:text-slate-100">AI Proctor</h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Багшийн хяналтын самбар · {teacher.name}</p>
          </div>
        </div>

        <div className="flex items-center gap-5">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 text-xs">
            <span className={`relative flex w-2 h-2`}>
              <span className={`absolute inline-flex w-full h-full rounded-full opacity-75 ${
                connectionStatus === 'connected' ? 'bg-emerald-400 animate-ping' :
                connectionStatus === 'connecting' ? 'bg-amber-400' : 'bg-red-400'
              }`} />
              <span className={`relative inline-flex w-2 h-2 rounded-full ${
                connectionStatus === 'connected' ? 'bg-emerald-500' :
                connectionStatus === 'connecting' ? 'bg-amber-500' : 'bg-red-500'
              }`} />
            </span>
            <span className="font-medium text-slate-700 dark:text-slate-300">
              {connectionStatus === 'connected' ? 'Холбогдсон' :
               connectionStatus === 'connecting' ? 'Холбогдож байна' : 'Холболтгүй'}
            </span>
          </div>
          <ThemeToggle />
          <button
            onClick={() => router.push('/history')}
            className="ufe-caps text-xs text-slate-700 dark:text-slate-300 hover:text-ufe-600 dark:hover:text-ufe-400 transition-colors"
            title="Архивласан шалгалтын түүх"
          >
            Түүх
          </button>
          <button
            onClick={handleArchiveAll}
            className="ufe-caps text-xs text-amber-600 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-300 transition-colors"
            title="Бүх дууссан шалгалтыг түүх рүү шилжүүлэх"
          >
            Архивлах
          </button>
          <button
            onClick={handleLogout}
            className="ufe-caps text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 transition-colors"
          >
            Гарах
          </button>
        </div>
      </header>

      <StatsBar students={allList} />

      {criticalAlerts.length > 0 && (
        <div className="flex items-center gap-3 px-4 py-2 border-b bg-gradient-to-r from-red-50 via-red-50 to-transparent dark:from-red-950/40 dark:via-red-950/30 border-red-200 dark:border-red-900/40">
          <span className="flex items-center gap-1.5 flex-shrink-0 text-xs font-bold text-red-300 uppercase tracking-wider">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
            Сэжигтэй
          </span>
          <div className="flex items-center gap-4 overflow-x-auto">
            {criticalAlerts.map((alert, i) => (
              <span key={i} className="text-xs font-medium text-red-300 whitespace-nowrap animate-alert-slide">{alert}</span>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        <aside className="flex flex-col w-72 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800">
          <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800">
            <div className="flex items-center justify-between mb-2.5">
              <span className="text-xs font-semibold tracking-wider uppercase text-slate-500 dark:text-slate-400">Оюутнууд</span>
              <span className="text-xs bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-0.5 rounded-md font-medium tabular-nums">{studentList.length}</span>
            </div>
            <div className="relative">
              <svg
                className="absolute w-3.5 h-3.5 -translate-y-1/2 left-2.5 top-1/2 text-slate-500 dark:text-slate-400"
                viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              >
                <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Хайх..."
                className="w-full pl-8 pr-2 py-1.5 text-xs rounded-md bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {studentList.length === 0 && (
              <div className="flex flex-col items-center justify-center px-4 py-16 text-center">
                <div className="flex items-center justify-center w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800 mb-3">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-slate-500 dark:text-slate-400">
                    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
                  </svg>
                </div>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-300">Оюутан байхгүй</p>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Оюутан холбогдоход энд харагдана</p>
              </div>
            )}
            {studentList.map(s => {
              const isSelected = selected === s.id
              const highRisk = s.riskScore >= 60
              return (
                <div
                  key={s.id}
                  onClick={() => setSelected(s.id)}
                  className={`px-4 py-3 cursor-pointer border-l-2 transition-all ${
                    isSelected
                      ? 'bg-blue-50 dark:bg-blue-950/50 border-l-blue-600'
                      : 'border-l-transparent hover:bg-slate-100 dark:bg-slate-800 hover:border-l-slate-200'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className="relative">
                      <div className={`w-9 h-9 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0 ${
                        s.riskScore >= 60 ? 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300' :
                        s.riskScore >= 30 ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300' : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300'
                      } ${highRisk ? 'animate-pulse-ring' : ''}`}>
                        {s.name.charAt(0)}
                      </div>
                      <span className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-white ${
                        s.online ? 'bg-emerald-500' : 'bg-slate-300'
                      }`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate text-slate-900 dark:text-slate-100">{s.name}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400 truncate">{s.id}</div>
                    </div>
                    <div className="flex-shrink-0 text-right">
                      <div className={`text-base font-bold tabular-nums ${severityTextColor(s.riskScore)}`}>{Math.round(s.riskScore)}</div>
                      <div className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${riskBadge(s.riskScore)}`}>
                        {s.riskScore >= 60 ? 'Өндөр' : s.riskScore >= 30 ? 'Дунд' : 'Хэвийн'}
                      </div>
                    </div>
                  </div>
                  <div className="h-1 mt-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div className={`h-full rounded-full transition-all duration-700 ${severityColor(s.riskScore)}`}
                         style={{ width: `${s.riskScore}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        </aside>

        <main className="flex-1 p-6 overflow-y-auto bg-grid-subtle">
          {!selectedStudent ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500/10 to-indigo-500/10 mb-4">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-blue-400">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
                </svg>
              </div>
              <p className="ufe-caps text-xs text-slate-800 dark:text-slate-200">Оюутан сонгогдоогүй байна</p>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Зүүн талын жагсаалтаас оюутан сонгож харна уу</p>
            </div>
          ) : (
            <div className="flex flex-col max-w-6xl gap-5 mx-auto animate-fade-up">
              <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
                <div className="md:col-span-2 p-5 bg-white dark:bg-slate-900 border rounded-xl border-slate-200 dark:border-slate-800 shadow-sm">
                  <div className="flex items-start justify-between mb-5">
                    <div className="flex items-center gap-3">
                      <div className={`w-11 h-11 rounded-xl flex items-center justify-center text-base font-bold flex-shrink-0 ${
                        selectedStudent.riskScore >= 60 ? 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300' :
                        selectedStudent.riskScore >= 30 ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300' : 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'
                      }`}>
                        {selectedStudent.name.charAt(0)}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">{selectedStudent.name}</h2>
                          <span className={`w-2 h-2 rounded-full ${selectedStudent.online ? 'bg-emerald-500 animate-pulse' : 'bg-slate-300'}`} />
                          <span className="text-xs text-slate-500 dark:text-slate-400">{selectedStudent.online ? 'Идэвхтэй' : 'Холболтгүй'}</span>
                        </div>
                        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{selectedStudent.id} · {selectedStudent.department}</p>
                        <p className="text-xs mt-0.5">
                          {selectedStudent.submittedAt
                            ? <span className="text-emerald-600 dark:text-emerald-400">Илгээсэн · {formatTime(selectedStudent.submittedAt)}</span>
                            : selectedStudent.active
                              ? <span className="text-blue-600 dark:text-blue-400">Шалгалт явагдаж байна</span>
                              : <span className="text-slate-400">Шалгалт эхлээгүй</span>}
                        </p>
                      </div>
                    </div>
                    {selectedStudent.sessionId && (
                      <button
                        onClick={() => handleShowAnswers(selectedStudent)}
                        className="text-xs font-medium px-3 py-1.5 rounded-md border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
                      >
                        Хариулт харах
                      </button>
                    )}
                  </div>

                  {selectedStudent.decision !== 'pending' ? (
                    <div className={`flex items-center justify-between text-sm font-medium px-4 py-3 rounded-lg border ${severityBg(selectedStudent.riskScore)}`}>
                      <span className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${severityColor(selectedStudent.riskScore)}`} />
                        {selectedStudent.decision === 'flagged' ? 'Сэжигтэй гэж тэмдэглэгдсэн' : 'Зөрчилгүй гэж баталгаажуулагдсан'}
                      </span>
                      <button onClick={() => handleDecision(selectedStudent.id, 'pending' as any)}
                              className="text-xs font-medium text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:text-slate-200">
                        Шийдвэр өөрчлөх
                      </button>
                    </div>
                  ) : (
                    <div className="flex gap-3">
                      <button onClick={() => handleDecision(selectedStudent.id, 'flagged')}
                              className="flex-1 px-4 py-2.5 text-sm font-semibold text-red-700 dark:text-red-300 border border-red-200 dark:border-red-900/50 rounded-lg bg-red-50 dark:bg-red-950/30 hover:bg-red-100 dark:hover:bg-red-900/50 transition-colors">
                        Сэжигтэй тэмдэглэх
                      </button>
                      <button onClick={() => handleDecision(selectedStudent.id, 'cleared')}
                              className="flex-1 px-4 py-2.5 text-sm font-semibold border rounded-lg text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-900/40 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 transition-colors">
                        Зөрчилгүй баталгаажуулах
                      </button>
                    </div>
                  )}

                  <div className="mt-5 pt-5 border-t border-slate-200 dark:border-slate-800">
                    <Sparkline events={selectedStudent.events} windowMinutes={30} />
                  </div>
                </div>

                <div className="p-5 bg-white dark:bg-slate-900 border rounded-xl border-slate-200 dark:border-slate-800 shadow-sm flex flex-col items-center justify-center">
                  <p className="text-[10px] font-semibold tracking-wider uppercase text-slate-500 dark:text-slate-400 mb-3">
                    Эрсдэлийн оноо
                  </p>
                  <RiskGauge score={selectedStudent.riskScore} />
                  <div className="w-full mt-4 pt-4 border-t border-slate-200 dark:border-slate-800">
                    <div className="flex justify-between text-xs">
                      <span className="text-slate-500 dark:text-slate-400">Үйлдэл</span>
                      <span className="font-semibold tabular-nums text-slate-800 dark:text-slate-200">{selectedStudent.events.length}</span>
                    </div>
                    <div className="flex justify-between mt-1.5 text-xs">
                      <span className="text-slate-500 dark:text-slate-400">Өндөр</span>
                      <span className="font-semibold tabular-nums text-red-400">
                        {selectedStudent.events.filter(e => e.severity === 'high').length}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="overflow-hidden bg-white dark:bg-slate-900 border rounded-xl border-slate-200 dark:border-slate-800 shadow-sm">
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-800">
                  <div className="flex items-center gap-2">
                    <span className="relative flex w-2 h-2">
                      <span className="absolute inline-flex w-full h-full rounded-full opacity-75 animate-ping bg-red-400" />
                      <span className="relative inline-flex w-2 h-2 rounded-full bg-red-500" />
                    </span>
                    <h3 className="ufe-caps text-xs text-slate-800 dark:text-slate-200">Камерийн зураг</h3>
                    <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-900/40">LIVE</span>
                  </div>
                </div>
                <div className="relative flex items-center justify-center bg-white dark:bg-slate-900 aspect-video">
                  <img
                    ref={videoImgRef}
                    alt="Live"
                    className={`w-full h-full object-contain ${hasFrame ? '' : 'hidden'}`}
                  />
                  {!hasFrame && (
                    <div className="flex flex-col items-center gap-3 text-slate-500 dark:text-slate-400">
                      {selectedStudent.online ? (
                        <>
                          <div className="w-8 h-8 border-2 border-slate-700 border-t-blue-500 rounded-full animate-spin" />
                          <p className="text-xs">Зураг ачаалж байна...</p>
                        </>
                      ) : (
                        <>
                          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M1 1l22 22" /><path d="M21 21H3a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3" /><path d="M21 12V5a2 2 0 0 0-2-2h-7" />
                          </svg>
                          <p className="text-xs">Оюутан холбогдоогүй байна</p>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>

              <div className="overflow-hidden bg-white dark:bg-slate-900 border rounded-xl border-slate-200 dark:border-slate-800 shadow-sm">
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-800">
                  <h3 className="ufe-caps text-xs text-slate-800 dark:text-slate-200">Бүртгэгдсэн үйлдлүүд</h3>
                  <div className="flex items-center gap-3">
                    <span className="text-xs bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-0.5 rounded-md font-medium tabular-nums">{selectedStudent.events.length}</span>
                    <button
                      onClick={() => handleDownloadCsv(selectedStudent)}
                      className="flex items-center gap-1 text-xs font-medium text-blue-400 hover:text-blue-300 transition-colors"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                      Тайлан татах
                    </button>
                    {selectedStudent.events.length > 0 && (
                      <button
                        onClick={() => handleClear(selectedStudent.id)}
                        className="pl-3 text-xs font-medium border-l text-slate-500 dark:text-slate-400 hover:text-red-400 border-slate-200 dark:border-slate-800 transition-colors"
                      >
                        Цэвэрлэх
                      </button>
                    )}
                  </div>
                </div>

                {selectedStudent.events.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-center">
                    <div className="flex items-center justify-center w-10 h-10 rounded-full bg-emerald-50 dark:bg-emerald-950/30 mb-3">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-400">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </div>
                    <p className="text-sm font-medium text-slate-700 dark:text-slate-300">Бүх зүйл хэвийн</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Одоохондоо үйлдэл бүртгэгдээгүй</p>
                  </div>
                ) : (
                  <div className="divide-y divide-slate-200 dark:divide-slate-800">
                    {selectedStudent.events.map((ev, i) => (
                      <div key={i} className="flex items-start gap-3 px-5 py-3 transition-colors hover:bg-slate-100 dark:bg-slate-800">
                        <div className={`flex items-center justify-center w-7 h-7 rounded-lg flex-shrink-0 mt-0.5 ${
                          ev.severity === 'high' ? 'bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400' :
                          ev.severity === 'medium' ? 'bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400' : 'bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400'
                        }`}>
                          <EventIcon type={ev.event_type} />
                        </div>
                        {ev.snapshot ? (
                          <AuthImage
                            snapshot={ev.snapshot}
                            onOpen={setSnapshotPreview}
                            className="flex-shrink-0 object-cover w-16 h-12 border rounded-md cursor-pointer border-slate-200 dark:border-slate-800 hover:border-blue-400 transition-colors"
                          />
                        ) : (
                          <div className="flex-shrink-0 w-16 h-12 rounded-md bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800" />
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{ev.message}</p>
                          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 flex items-center gap-2">
                            <span>{EVENT_LABEL[ev.event_type] || ev.event_type}</span>
                            <span className="text-slate-700 dark:text-slate-300">·</span>
                            <span className="tabular-nums">{formatTime(ev.timestamp)}</span>
                          </p>
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

      {submission && (
        <div onClick={() => setSubmission(null)}
             className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/60 backdrop-blur-sm">
          <div onClick={e => e.stopPropagation()}
               className="w-full max-w-2xl max-h-[85vh] overflow-y-auto bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xl">
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-800">
              <div>
                <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Шалгалтын хариулт</h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  {submission.submitted_at
                    ? `Илгээсэн: ${formatTime(submission.submitted_at)}${submission.auto_submitted ? ' (хугацаа дуусч автоматаар)' : ''}`
                    : `Илгээгээгүй · сүүлд хадгалсан: ${submission.updated_at ? formatTime(submission.updated_at) : '—'}`}
                </p>
              </div>
              <button onClick={() => setSubmission(null)} className="text-xs text-slate-500 hover:text-slate-900 dark:hover:text-slate-100">Хаах</button>
            </div>
            <div className="divide-y divide-slate-200 dark:divide-slate-800">
              {submission.items.map((it, i) => (
                <div key={it.id} className="px-5 py-4">
                  <p className="text-xs font-semibold text-blue-600 dark:text-blue-400 mb-1">Асуулт {i + 1}</p>
                  <p className="text-sm text-slate-800 dark:text-slate-200 mb-2">{it.text}</p>
                  <p className={`text-sm whitespace-pre-wrap rounded-md px-3 py-2 ${it.answer
                    ? 'bg-slate-50 dark:bg-slate-950 text-slate-700 dark:text-slate-300'
                    : 'text-slate-400 italic'}`}>
                    {it.answer || 'Хариулаагүй'}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
