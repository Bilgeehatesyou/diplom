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
  riskScore: number
  events: LiveEvent['event'][]
  decision: 'pending' | 'flagged' | 'cleared'
}

const STUDENT_NAMES: Record<string, string> = {
  student_001: 'Б.Билгээ',
  student_002: 'Г.Мөнхбат',
  student_003: 'Д.Сарнай',
}

export default function TeacherDashboard() {
  const wsRef    = useRef<WebSocket | null>(null)
  const [students, setStudents] = useState<Record<string, StudentState>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [alerts, setAlerts]     = useState<string[]>([])

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(`${process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'}/ws/teacher`)
      ws.onmessage = (e) => {
        const data: LiveEvent = JSON.parse(e.data)
        const { student_id, event } = data
        const sevScore = event.severity === 'high' ? 15 : event.severity === 'medium' ? 7 : 3

        setStudents(prev => {
          const s = prev[student_id] || {
            id: student_id,
            name: STUDENT_NAMES[student_id] || student_id,
            riskScore: 0,
            events: [],
            decision: 'pending',
          }
          return {
            ...prev,
            [student_id]: {
              ...s,
              riskScore: Math.min(100, s.riskScore + sevScore),
              events: [event, ...s.events].slice(0, 50),
            },
          }
        })

        if (event.severity === 'high') {
          const name = STUDENT_NAMES[student_id] || student_id
          setAlerts(p => [`🚨 ${name}: ${event.message}`, ...p].slice(0, 5))
        }
      }
      ws.onclose = () => setTimeout(connect, 3000)
      wsRef.current = ws
    }
    connect()
    return () => wsRef.current?.close()
  }, [])

  const decide = (id: string, d: 'flagged' | 'cleared') => {
    setStudents(p => ({ ...p, [id]: { ...p[id], decision: d } }))
  }

  const list     = Object.values(students)
  const selStudent = selected ? students[selected] : null

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">

      {/* Topbar */}
      <div className="bg-white border-b px-6 py-3 flex items-center justify-between">
        <div>
          <div className="font-bold text-gray-900">AI Proctor — Багшийн самбар</div>
          <div className="text-xs text-gray-500">СЭЗИС · Мэдээллийн систем · Улирлын шалгалт</div>
        </div>
        <div className="flex items-center gap-2 text-xs bg-red-50 text-red-600 px-3 py-1.5 rounded-full font-semibold">
          <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" /> ШУУД ХЯНАЛТ
        </div>
      </div>

      {/* Alerts */}
      {alerts.length > 0 && (
        <div className="bg-red-50 border-b border-red-200 px-6 py-2 flex items-center gap-4 overflow-x-auto">
          {alerts.map((a, i) => (
            <span key={i} className="text-xs text-red-700 whitespace-nowrap">{a}</span>
          ))}
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">

        {/* Sidebar */}
        <div className="w-64 bg-white border-r overflow-y-auto">
          <div className="p-3 border-b text-xs font-semibold text-gray-400 uppercase tracking-wide">
            Оюутнууд ({list.length})
          </div>
          {list.length === 0 && (
            <div className="p-6 text-center text-sm text-gray-400">
              Оюутан холбогдохыг хүлээж байна...
            </div>
          )}
          {list.map(s => (
            <div
              key={s.id}
              onClick={() => setSelected(s.id)}
              className={`p-3 flex items-center gap-3 cursor-pointer border-l-4 transition-colors
                ${selected === s.id ? 'bg-blue-50 border-blue-500' : 'border-transparent hover:bg-gray-50'}`}
            >
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold
                ${s.riskScore > 60 ? 'bg-red-100 text-red-700' : s.riskScore > 30 ? 'bg-yellow-100 text-yellow-700' : 'bg-green-100 text-green-700'}`}>
                {s.name.charAt(0)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{s.name}</div>
                <div className="text-xs text-gray-400">{s.events.length} flag</div>
              </div>
              <div className={`text-xs font-bold ${s.riskScore > 60 ? 'text-red-600' : s.riskScore > 30 ? 'text-yellow-600' : 'text-green-600'}`}>
                {s.riskScore}
              </div>
            </div>
          ))}
        </div>

        {/* Main */}
        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-4">
          {!selStudent ? (
            <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
              Зүүн талаас оюутан сонгоно уу
            </div>
          ) : (
            <>
              {/* Student header */}
              <div className="bg-white rounded-xl border p-5">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h2 className="text-lg font-bold">{selStudent.name}</h2>
                    <div className="text-sm text-gray-500">{selStudent.id}</div>
                  </div>
                  <div className="text-right">
                    <div className={`text-3xl font-bold ${selStudent.riskScore > 60 ? 'text-red-600' : selStudent.riskScore > 30 ? 'text-yellow-600' : 'text-green-600'}`}>
                      {selStudent.riskScore}
                    </div>
                    <div className="text-xs text-gray-400">эрсдэлийн оноо</div>
                  </div>
                </div>

                {/* Risk bar */}
                <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden mb-4">
                  <div
                    className={`h-full rounded-full transition-all ${selStudent.riskScore > 60 ? 'bg-red-500' : selStudent.riskScore > 30 ? 'bg-yellow-500' : 'bg-green-500'}`}
                    style={{ width: `${selStudent.riskScore}%` }}
                  />
                </div>

                {/* Decision */}
                {selStudent.decision !== 'pending' ? (
                  <div className={`text-sm font-semibold px-3 py-2 rounded-lg ${selStudent.decision === 'flagged' ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
                    {selStudent.decision === 'flagged' ? '🚩 Сэжигтэй гэж тэмдэглэгдсэн' : '✓ Зөрчилгүй гэж баталгаажуулагдсан'}
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <button onClick={() => decide(selStudent.id, 'flagged')}
                      className="px-4 py-2 text-sm font-semibold text-red-600 border border-red-200 rounded-lg hover:bg-red-50">
                      🚩 Сэжигтэй тэмдэглэх
                    </button>
                    <button onClick={() => decide(selStudent.id, 'cleared')}
                      className="px-4 py-2 text-sm font-semibold text-green-600 border border-green-200 rounded-lg hover:bg-green-50">
                      ✓ Зөрчилгүй баталгаажуулах
                    </button>
                  </div>
                )}
              </div>

              {/* Events */}
              <div className="bg-white rounded-xl border overflow-hidden">
                <div className="p-4 border-b font-semibold text-sm">
                  Бүртгэгдсэн үйлдлүүд ({selStudent.events.length})
                </div>
                {selStudent.events.length === 0 ? (
                  <div className="p-6 text-center text-sm text-gray-400">Одоохондоо flag байхгүй</div>
                ) : (
                  selStudent.events.map((ev, i) => (
                    <div key={i} className="flex items-start gap-3 px-4 py-3 border-b last:border-0">
                      <div className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0
                        ${ev.severity === 'high' ? 'bg-red-500' : ev.severity === 'medium' ? 'bg-yellow-500' : 'bg-blue-400'}`} />
                      <div className="flex-1">
                        <div className="text-sm font-medium">{ev.message}</div>
                        <div className="text-xs text-gray-400">{new Date(ev.timestamp).toLocaleTimeString('mn-MN')}</div>
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium
                        ${ev.severity === 'high' ? 'bg-red-50 text-red-600' : ev.severity === 'medium' ? 'bg-yellow-50 text-yellow-600' : 'bg-blue-50 text-blue-600'}`}>
                        {ev.severity === 'high' ? 'Өндөр' : ev.severity === 'medium' ? 'Дунд' : 'Бага'}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
