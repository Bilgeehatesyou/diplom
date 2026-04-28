'use client'
import { useEffect, useState, useRef } from 'react'

interface LiveEvent {
  student_id: string
  event: {
    type: string
    severity: 'low' | 'medium' | 'high'
    timestamp: string
    message: string
  }
}

interface StudentState {
  id: string
  name: string
  studentId: string
  riskScore: number
  events: LiveEvent['event'][]
  decision: 'pending' | 'flagged' | 'cleared'
}

const STUDENTS: Record<string, { name: string; code: string }> = {
  student_001: { name: 'Б.Билгээ', code: 'МСМ-2101' },
  student_002: { name: 'Г.Мөнхбат', code: 'МСМ-2102' },
  student_003: { name: 'Д.Сарнай', code: 'МСМ-2103' },
}

function getSeverityColor(score: number): string {
  if (score >= 60) return 'bg-red-500'
  if (score >= 30) return 'bg-amber-500'
  return 'bg-emerald-500'
}

function getSeverityTextColor(score: number): string {
  if (score >= 60) return 'text-red-600'
  if (score >= 30) return 'text-amber-600'
  return 'text-emerald-600'
}

function getSeverityBg(score: number): string {
  if (score >= 60) return 'bg-red-50 border-red-200'
  if (score >= 30) return 'bg-amber-50 border-amber-200'
  return 'bg-emerald-50 border-emerald-200'
}

function getRiskBadge(score: number): string {
  if (score >= 60) return 'text-red-700 bg-red-100'
  if (score >= 30) return 'text-amber-700 bg-amber-100'
  return 'text-emerald-700 bg-emerald-100'
}

function EventSeverityDot({ severity }: { severity: string }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full flex-shrink-0 mt-[5px] ${
        severity === 'high' ? 'bg-red-500' :
        severity === 'medium' ? 'bg-amber-400' : 'bg-blue-400'
      }`}
    />
  )
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString('mn-MN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function TeacherDashboard() {
  const wsRef = useRef<WebSocket | null>(null)
  const [students, setStudents] = useState<Record<string, StudentState>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [criticalAlerts, setCriticalAlerts] = useState<string[]>([])
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(`${process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'}/ws/teacher`)
      setConnectionStatus('connecting')

      ws.onopen = () => setConnectionStatus('connected')
      ws.onclose = () => {
        setConnectionStatus('disconnected')
        setTimeout(connect, 3000)
      }
      ws.onerror = () => setConnectionStatus('disconnected')

      ws.onmessage = (e) => {
        const data: LiveEvent = JSON.parse(e.data)
        const { student_id, event } = data
        const scoreMap: Record<string, number> = { high: 15, medium: 7, low: 3 }

        setStudents(prev => {
          const info = STUDENTS[student_id] || { name: student_id, code: '—' }
          const existing = prev[student_id] || {
            id: student_id,
            name: info.name,
            studentId: info.code,
            riskScore: 0,
            events: [],
            decision: 'pending' as const,
          }
          return {
            ...prev,
            [student_id]: {
              ...existing,
              riskScore: Math.min(100, existing.riskScore + (scoreMap[event.severity] ?? 3)),
              events: [event, ...existing.events].slice(0, 100),
            },
          }
        })

        if (event.severity === 'high') {
          const info = STUDENTS[student_id] || { name: student_id }
          const msg = `[${formatTime(event.timestamp)}] ${info.name}: ${event.message}`
          setCriticalAlerts(p => [msg, ...p].slice(0, 8))
        }
      }

      wsRef.current = ws
    }
    connect()
    return () => wsRef.current?.close()
  }, [])

  const handleDecision = (id: string, d: 'flagged' | 'cleared') => {
    setStudents(p => ({ ...p, [id]: { ...p[id], decision: d } }))
  }

  const studentList = Object.values(students)
  const selectedStudent = selected ? students[selected] : null

  return (
    <div className="min-h-screen flex flex-col bg-slate-100">
      {/* ── Header ── */}
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-600 rounded-md flex items-center justify-center">
            <span className="text-white text-sm font-bold">AP</span>
          </div>
          <div>
            <h1 className="text-sm font-semibold text-slate-800 leading-none">AI Proctor</h1>
            <p className="text-xs text-slate-500 mt-0.5">Багшийн хяналтын самбар</p>
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
          <div className="text-xs text-slate-500 border-l border-slate-200 pl-6">
            СЭЗИС · Мэдээллийн систем · Улирлын шалгалт
          </div>
        </div>
      </header>

      {/* ── Critical Alerts Bar ── */}
      {criticalAlerts.length > 0 && (
        <div className="bg-red-50 border-b border-red-200 px-4 py-2 flex items-center gap-3">
          <span className="text-xs font-semibold text-red-600 flex-shrink-0">ЦАХИЛГААН:</span>
          <div className="flex items-center gap-4 overflow-x-auto">
            {criticalAlerts.map((alert, i) => (
              <span key={i} className="text-xs text-red-700 whitespace-nowrap font-medium">{alert}</span>
            ))}
          </div>
        </div>
      )}

      {/* ── Main Layout ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── Student List Sidebar ── */}
        <aside className="w-72 bg-white border-r border-slate-200 flex flex-col">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Оюутнууд</span>
            <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-medium">
              {studentList.length}
            </span>
          </div>

          <div className="flex-1 overflow-y-auto">
            {studentList.length === 0 && (
              <div className="flex flex-col items-center justify-center py-16 text-slate-400">
                <svg className="w-10 h-10 mb-3 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                <p className="text-sm">Оюутан холбогдохыг хүлээж байна</p>
              </div>
            )}
            {studentList.map(s => {
              const isSelected = selected === s.id
              return (
                <div
                  key={s.id}
                  onClick={() => setSelected(s.id)}
                  className={`px-4 py-3 cursor-pointer border-l-3 transition-colors border-l-2 ${
                    isSelected
                      ? 'bg-blue-50 border-l-blue-600'
                      : 'border-l-transparent hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0 ${
                      s.riskScore >= 60 ? 'bg-red-100 text-red-700' :
                      s.riskScore >= 30 ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'
                    }`}>
                      {s.name.charAt(0)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-slate-800 truncate">{s.name}</div>
                      <div className="text-xs text-slate-400">{s.studentId}</div>
                    </div>
                    <div className="flex-shrink-0 text-right">
                      <div className={`text-sm font-bold ${getSeverityTextColor(s.riskScore)}`}>
                        {s.riskScore}
                      </div>
                      <div className={`text-xs px-1.5 py-0.5 rounded font-medium ${getRiskBadge(s.riskScore)}`}>
                        {s.riskScore >= 60 ? 'Өндөр' : s.riskScore >= 30 ? 'Дунд' : 'Хэвийн'}
                      </div>
                    </div>
                  </div>

                  {/* Risk bar */}
                  <div className="mt-2 h-1 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${getSeverityColor(s.riskScore)}`}
                      style={{ width: `${s.riskScore}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </aside>

        {/* ── Detail Panel ── */}
        <main className="flex-1 overflow-y-auto p-6">
          {!selectedStudent ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-400">
              <svg className="w-12 h-12 mb-4 opacity-25" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              <p className="text-sm">Зүүн талын жагсаалтаас оюутан сонгоно уу</p>
            </div>
          ) : (
            <div className="flex flex-col gap-5 max-w-4xl">
              {/* Student Info Card */}
              <div className="bg-white rounded-lg border border-slate-200 p-5">
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h2 className="text-base font-semibold text-slate-800">{selectedStudent.name}</h2>
                    <p className="text-xs text-slate-500 mt-0.5">{selectedStudent.id} · {selectedStudent.studentId}</p>
                  </div>
                  <div className="text-right">
                    <div className={`text-3xl font-bold ${getSeverityTextColor(selectedStudent.riskScore)}`}>
                      {selectedStudent.riskScore}
                    </div>
                    <div className="text-xs text-slate-400 mt-0.5">эрсдэлийн оноо</div>
                  </div>
                </div>

                {/* Risk progress bar */}
                <div className="mb-4">
                  <div className="flex justify-between text-xs text-slate-500 mb-1.5">
                    <span>Эрсдэлийн түвшин</span>
                    <span>{selectedStudent.riskScore >= 60 ? 'Өндөр' : selectedStudent.riskScore >= 30 ? 'Дунд' : 'Бага'}</span>
                  </div>
                  <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-700 ${getSeverityColor(selectedStudent.riskScore)}`}
                      style={{ width: `${selectedStudent.riskScore}%` }}
                    />
                  </div>
                </div>

                {/* Decision buttons or status */}
                {selectedStudent.decision !== 'pending' ? (
                  <div className={`flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border ${getSeverityBg(selectedStudent.riskScore)}`}>
                    <span className={`w-2 h-2 rounded-full ${getSeverityColor(selectedStudent.riskScore)}`} />
                    {selectedStudent.decision === 'flagged'
                      ? 'Сэжигтэй гэж тэмдэглэгдсэн'
                      : 'Зөрчилгүй гэж баталгаажуулагдсан'}
                  </div>
                ) : (
                  <div className="flex gap-3">
                    <button
                      onClick={() => handleDecision(selectedStudent.id, 'flagged')}
                      className="px-4 py-2 text-sm font-medium text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition-colors"
                    >
                      Сэжигтэй тэмдэглэх
                    </button>
                    <button
                      onClick={() => handleDecision(selectedStudent.id, 'cleared')}
                      className="px-4 py-2 text-sm font-medium text-emerald-600 bg-emerald-50 border border-emerald-200 rounded-lg hover:bg-emerald-100 transition-colors"
                    >
                      Зөрчилгүй баталгаажуулах
                    </button>
                  </div>
                )}
              </div>

              {/* Events Log */}
              <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
                <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-700">Бүртгэгдсэн үйлдлүүд</h3>
                  <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-medium">
                    {selectedStudent.events.length}
                  </span>
                </div>

                {selectedStudent.events.length === 0 ? (
                  <div className="py-12 text-center text-sm text-slate-400">
                    Одоохондоо үйлдэл бүртгэгдээгүй
                  </div>
                ) : (
                  <div className="divide-y divide-slate-100">
                    {selectedStudent.events.map((ev, i) => (
                      <div key={i} className="px-5 py-3 flex items-start gap-3 hover:bg-slate-50 transition-colors">
                        <EventSeverityDot severity={ev.severity} />
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
    </div>
  )
}