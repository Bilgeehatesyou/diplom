'use client'
import { useEffect, useState, useRef } from 'react'
import { useRouter } from 'next/navigation'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const WS  = process.env.NEXT_PUBLIC_WS_URL  || 'ws://localhost:8000'

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
  risk_score: number
  decision: 'pending' | 'flagged' | 'cleared'
  online: boolean
  started_at: string | null
  ended_at: string | null
  events: RiskEv[]
}

interface StudentState {
  id: string
  name: string
  department: string
  riskScore: number
  events: RiskEv[]
  decision: 'pending' | 'flagged' | 'cleared'
  online: boolean
}

function severityColor(score: number) {
  if (score >= 60) return 'bg-red-500'
  if (score >= 30) return 'bg-amber-500'
  return 'bg-emerald-500'
}
function severityTextColor(score: number) {
  if (score >= 60) return 'text-red-600'
  if (score >= 30) return 'text-amber-600'
  return 'text-emerald-600'
}
function severityBg(score: number) {
  if (score >= 60) return 'bg-red-50 border-red-200'
  if (score >= 30) return 'bg-amber-50 border-amber-200'
  return 'bg-emerald-50 border-emerald-200'
}
function riskBadge(score: number) {
  if (score >= 60) return 'text-red-700 bg-red-100'
  if (score >= 30) return 'text-amber-700 bg-amber-100'
  return 'text-emerald-700 bg-emerald-100'
}
function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('mn-MN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function TeacherDashboard() {
  const router = useRouter()
  const wsRef = useRef<WebSocket | null>(null)
  const selectedRef = useRef<string | null>(null)
  const videoImgRef = useRef<HTMLImageElement | null>(null)
  const currentBlobUrlRef = useRef<string | null>(null)
  const [teacher, setTeacher] = useState<{ teacher_id: number; name: string } | null>(null)
  const [students, setStudents] = useState<Record<string, StudentState>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [criticalAlerts, setCriticalAlerts] = useState<string[]>([])
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')
  const [hasFrame, setHasFrame] = useState(false)
  const [snapshotPreview, setSnapshotPreview] = useState<string | null>(null)

  useEffect(() => { selectedRef.current = selected }, [selected])

  // Auth gate
  useEffect(() => {
    const raw = localStorage.getItem('ap_teacher')
    if (!raw) { router.push('/login'); return }
    try { setTeacher(JSON.parse(raw)) } catch { router.push('/login') }
  }, [router])

  // Rehydrate from DB on mount/refresh
  useEffect(() => {
    if (!teacher) return
    fetch(`${API}/api/dashboard`)
      .then(r => r.json())
      .then((rows: DashboardRow[]) => {
        const map: Record<string, StudentState> = {}
        for (const r of rows) {
          map[r.id] = {
            id: r.id, name: r.name, department: r.department,
            riskScore: Math.min(100, r.risk_score), events: r.events,
            decision: r.decision, online: r.online,
          }
        }
        setStudents(map)
      })
      .catch(() => {})
  }, [teacher])

  // WS connection
  useEffect(() => {
    if (!teacher) return
    const connect = () => {
      const ws = new WebSocket(`${WS}/ws/teacher`)
      ws.binaryType = 'blob'
      setConnectionStatus('connecting')

      ws.onopen = () => {
        setConnectionStatus('connected')
        if (selectedRef.current) {
          ws.send(JSON.stringify({ action: 'watch', student_id: selectedRef.current }))
        }
      }
      ws.onclose = () => {
        setConnectionStatus('disconnected')
        setTimeout(connect, 3000)
      }
      ws.onerror = () => setConnectionStatus('disconnected')

      ws.onmessage = (e) => {
        // Binary message = video frame for currently-watched student.
        // Update <img> directly via ref to avoid re-rendering the whole dashboard.
        if (e.data instanceof Blob) {
          const url = URL.createObjectURL(e.data)
          if (videoImgRef.current) videoImgRef.current.src = url
          if (currentBlobUrlRef.current) URL.revokeObjectURL(currentBlobUrlRef.current)
          currentBlobUrlRef.current = url
          if (!hasFrame) setHasFrame(true)
          return
        }
        const data = JSON.parse(e.data)
        if (data.ack === 'decide') return

        // UI-only online/offline signals
        if (data.meta === 'online' || data.meta === 'offline') {
          setStudents(prev => {
            const sid = data.student_id
            if (!prev[sid]) return prev
            return { ...prev, [sid]: { ...prev[sid], online: data.meta === 'online' } }
          })
          return
        }

        const { student_id, event } = data
        if (!event) return

        const scoreMap: Record<string, number> = { high: 15, medium: 7, low: 3 }

        setStudents(prev => {
          const existing = prev[student_id] || {
            id: student_id, name: student_id, department: '—',
            riskScore: 0, events: [], decision: 'pending' as const, online: true,
          }
          return {
            ...prev,
            [student_id]: {
              ...existing,
              online: true,
              riskScore: Math.min(100, existing.riskScore + (scoreMap[event.severity] ?? 3)),
              events: [event, ...existing.events].slice(0, 100),
            },
          }
        })

        if (event.severity === 'high') {
          const stud = students[student_id]
          const name = stud?.name || student_id
          const msg = `[${formatTime(event.timestamp)}] ${name}: ${event.message}`
          setCriticalAlerts(p => [msg, ...p].slice(0, 8))
        }
      }

      wsRef.current = ws
    }
    connect()
    return () => { wsRef.current?.close() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teacher])

  // Slow score decay (mirrors backend) so UI stays in sync
  useEffect(() => {
    if (!teacher) return
    const t = setInterval(() => {
      setStudents(prev => {
        const next = { ...prev }
        for (const id of Object.keys(next)) {
          if (next[id].online && next[id].riskScore > 0) {
            next[id] = { ...next[id], riskScore: Math.max(0, next[id].riskScore - 1) }
          }
        }
        return next
      })
    }, 30000)
    return () => clearInterval(t)
  }, [teacher])

  // Tell backend which student to stream frames for
  useEffect(() => {
    // Reset frame state when switching students
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
          // Cleared = false positive → zero risk score immediately
          riskScore: d === 'cleared' ? 0 : s.riskScore,
        },
      }
    })
  }

  const handleClear = async (id: string) => {
    if (!confirm('Энэ оюутны бүх бүртгэгдсэн үйлдлийг цэвэрлэх үү?\n(Мэдээлэл өгөгдлийн санд хадгалагдсан хэвээр үлдэнэ.)')) return
    try {
      const r = await fetch(`${API}/api/session/${id}/clear`, { method: 'POST' })
      if (!r.ok) throw new Error('clear failed')
      setStudents(p => {
        const s = p[id]
        if (!s) return p
        return { ...p, [id]: { ...s, events: [], riskScore: 0, decision: 'pending' } }
      })
    } catch (e) {
      console.error(e)
      alert('Цэвэрлэхэд алдаа гарлаа')
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('ap_teacher')
    router.push('/login')
  }

  if (!teacher) return null

  const studentList = Object.values(students).sort((a, b) => {
    if (a.online !== b.online) return a.online ? -1 : 1
    return b.riskScore - a.riskScore
  })
  const selectedStudent = selected ? students[selected] : null

  return (
    <div className="flex flex-col min-h-screen bg-slate-100">
      <header className="flex items-center justify-between px-6 py-3 bg-white border-b shadow-sm border-slate-200">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-8 h-8 bg-blue-600 rounded-md">
            <span className="text-sm font-bold text-white">AP</span>
          </div>
          <div>
            <h1 className="text-sm font-semibold leading-none text-slate-800">AI Proctor</h1>
            <p className="text-xs text-slate-500 mt-0.5">Багшийн хяналтын самбар · {teacher.name}</p>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className={`w-2 h-2 rounded-full ${
              connectionStatus === 'connected' ? 'bg-emerald-500' :
              connectionStatus === 'connecting' ? 'bg-amber-400 animate-pulse' : 'bg-red-400'
            }`} />
            {connectionStatus === 'connected' ? 'Серверт холбогдсон' :
             connectionStatus === 'connecting' ? 'Холбогдож байна...' : 'Сервертэй холболтоо алдсан'}
          </div>
          <button onClick={handleLogout} className="pl-6 text-xs border-l text-slate-400 hover:text-slate-600 border-slate-200">
            Гарах
          </button>
        </div>
      </header>

      {criticalAlerts.length > 0 && (
        <div className="flex items-center gap-3 px-4 py-2 border-b border-red-200 bg-red-50">
          <span className="flex-shrink-0 text-xs font-semibold text-red-600">СЭЖИГТЭЙ ҮЙЛДЭЛ:</span>
          <div className="flex items-center gap-4 overflow-x-auto">
            {criticalAlerts.map((alert, i) => (
              <span key={i} className="text-xs font-medium text-red-700 whitespace-nowrap">{alert}</span>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        <aside className="flex flex-col bg-white border-r w-72 border-slate-200">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
            <span className="text-xs font-semibold tracking-wider uppercase text-slate-500">Оюутнууд</span>
            <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-medium">{studentList.length}</span>
          </div>

          <div className="flex-1 overflow-y-auto">
            {studentList.length === 0 && (
              <div className="flex flex-col items-center justify-center py-16 text-slate-400">
                <p className="text-sm">Оюутан байхгүй</p>
              </div>
            )}
            {studentList.map(s => {
              const isSelected = selected === s.id
              return (
                <div
                  key={s.id}
                  onClick={() => setSelected(s.id)}
                  className={`px-4 py-3 cursor-pointer border-l-2 transition-colors ${
                    isSelected ? 'bg-blue-50 border-l-blue-600' : 'border-l-transparent hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className="relative">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0 ${
                        s.riskScore >= 60 ? 'bg-red-100 text-red-700' :
                        s.riskScore >= 30 ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'
                      }`}>
                        {s.name.charAt(0)}
                      </div>
                      <span className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-white ${
                        s.online ? 'bg-emerald-500' : 'bg-slate-300'
                      }`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate text-slate-800">{s.name}</div>
                      <div className="text-xs text-slate-400">{s.id}</div>
                    </div>
                    <div className="flex-shrink-0 text-right">
                      <div className={`text-sm font-bold ${severityTextColor(s.riskScore)}`}>{Math.round(s.riskScore)}</div>
                      <div className={`text-xs px-1.5 py-0.5 rounded font-medium ${riskBadge(s.riskScore)}`}>
                        {s.riskScore >= 60 ? 'Өндөр' : s.riskScore >= 30 ? 'Дунд' : 'Хэвийн'}
                      </div>
                    </div>
                  </div>
                  <div className="h-1 mt-2 overflow-hidden rounded-full bg-slate-100">
                    <div className={`h-full rounded-full transition-all duration-500 ${severityColor(s.riskScore)}`}
                         style={{ width: `${s.riskScore}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        </aside>

        <main className="flex-1 p-6 overflow-y-auto">
          {!selectedStudent ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-400">
              <p className="text-sm">Зүүн талын жагсаалтаас оюутан сонгоно уу</p>
            </div>
          ) : (
            <div className="flex flex-col max-w-5xl gap-5">
              <div className="p-5 bg-white border rounded-lg border-slate-200">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-base font-semibold text-slate-800">{selectedStudent.name}</h2>
                      <span className={`w-2 h-2 rounded-full ${selectedStudent.online ? 'bg-emerald-500 animate-pulse' : 'bg-slate-300'}`} />
                      <span className="text-xs text-slate-400">{selectedStudent.online ? 'Идэвхтэй' : 'Холболтгүй'}</span>
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">{selectedStudent.id} · {selectedStudent.department}</p>
                  </div>
                  <div className="text-right">
                    <div className={`text-3xl font-bold ${severityTextColor(selectedStudent.riskScore)}`}>{Math.round(selectedStudent.riskScore)}</div>
                    <div className="text-xs text-slate-400 mt-0.5">эрсдэлийн оноо</div>
                  </div>
                </div>

                <div className="mb-4">
                  <div className="flex justify-between text-xs text-slate-500 mb-1.5">
                    <span>Эрсдэлийн түвшин</span>
                    <span>{selectedStudent.riskScore >= 60 ? 'Өндөр' : selectedStudent.riskScore >= 30 ? 'Дунд' : 'Бага'}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                    <div className={`h-full rounded-full transition-all duration-700 ${severityColor(selectedStudent.riskScore)}`}
                         style={{ width: `${selectedStudent.riskScore}%` }} />
                  </div>
                </div>

                {selectedStudent.decision !== 'pending' ? (
                  <div className={`flex items-center justify-between text-sm font-medium px-4 py-2.5 rounded-lg border ${severityBg(selectedStudent.riskScore)}`}>
                    <span className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${severityColor(selectedStudent.riskScore)}`} />
                      {selectedStudent.decision === 'flagged' ? 'Сэжигтэй гэж тэмдэглэгдсэн' : 'Зөрчилгүй гэж баталгаажуулагдсан'}
                    </span>
                    <button onClick={() => handleDecision(selectedStudent.id, 'pending' as any)}
                            className="text-xs text-slate-500 hover:text-slate-700">
                      Шийдвэр өөрчлөх
                    </button>
                  </div>
                ) : (
                  <div className="flex gap-3">
                    <button onClick={() => handleDecision(selectedStudent.id, 'flagged')}
                            className="px-4 py-2 text-sm font-medium text-red-600 border border-red-200 rounded-lg bg-red-50 hover:bg-red-100">
                      Сэжигтэй тэмдэглэх
                    </button>
                    <button onClick={() => handleDecision(selectedStudent.id, 'cleared')}
                            className="px-4 py-2 text-sm font-medium border rounded-lg text-emerald-600 bg-emerald-50 border-emerald-200 hover:bg-emerald-100">
                      Зөрчилгүй баталгаажуулах
                    </button>
                  </div>
                )}
              </div>

              <div className="overflow-hidden bg-white border rounded-lg border-slate-200">
                <div className="px-5 py-3 border-b border-slate-100">
                  <h3 className="text-sm font-semibold text-slate-700">Камерийн зураг (амьд)</h3>
                </div>
                <div className="relative flex items-center justify-center bg-black aspect-video">
                  <img
                    ref={videoImgRef}
                    alt="Live"
                    className={`w-full h-full object-contain ${hasFrame ? '' : 'hidden'}`}
                  />
                  {!hasFrame && (
                    <div className="text-sm text-slate-400">
                      {selectedStudent.online ? 'Зураг ачаалж байна...' : 'Оюутан холбогдоогүй байна'}
                    </div>
                  )}
                </div>
              </div>

              <div className="overflow-hidden bg-white border rounded-lg border-slate-200">
                <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100">
                  <h3 className="text-sm font-semibold text-slate-700">Бүртгэгдсэн үйлдлүүд</h3>
                  <div className="flex items-center gap-3">
                    <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-medium">{selectedStudent.events.length}</span>
                    <a
                      href={`${API}/api/report/student/${selectedStudent.id}.csv`}
                      download
                      className="text-xs font-medium text-blue-600 hover:text-blue-700"
                    >
                      Тайлан татах ↓
                    </a>
                    {selectedStudent.events.length > 0 && (
                      <button
                        onClick={() => handleClear(selectedStudent.id)}
                        className="pl-3 text-xs font-medium border-l text-slate-500 hover:text-red-600 border-slate-200"
                      >
                        Цэвэрлэх ✕
                      </button>
                    )}
                  </div>
                </div>

                {selectedStudent.events.length === 0 ? (
                  <div className="py-12 text-sm text-center text-slate-400">Одоохондоо үйлдэл бүртгэгдээгүй</div>
                ) : (
                  <div className="divide-y divide-slate-100">
                    {selectedStudent.events.map((ev, i) => (
                      <div key={i} className="flex items-start gap-3 px-5 py-3 hover:bg-slate-50">
                        <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 mt-[5px] ${
                          ev.severity === 'high' ? 'bg-red-500' : ev.severity === 'medium' ? 'bg-amber-400' : 'bg-blue-400'
                        }`} />
                        {ev.snapshot ? (
                          <img
                            src={`${API}/api/incident/${ev.snapshot}`}
                            alt="snapshot"
                            onClick={() => setSnapshotPreview(`${API}/api/incident/${ev.snapshot}`)}
                            className="flex-shrink-0 object-cover w-16 h-12 border rounded cursor-pointer border-slate-200 hover:border-blue-400"
                          />
                        ) : (
                          <div className="flex-shrink-0 w-16 h-12 rounded bg-slate-50" />
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-slate-700">{ev.message}</p>
                          <p className="text-xs text-slate-400 mt-0.5">{formatTime(ev.timestamp)}</p>
                        </div>
                        <span className={`flex-shrink-0 text-xs px-2 py-0.5 rounded font-medium ${
                          ev.severity === 'high' ? 'bg-red-100 text-red-700' :
                          ev.severity === 'medium' ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'
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
          className="fixed inset-0 z-50 flex items-center justify-center p-8 cursor-pointer bg-black/80"
        >
          <img src={snapshotPreview} alt="snapshot" className="object-contain max-w-full max-h-full rounded" />
        </div>
      )}
    </div>
  )
}
