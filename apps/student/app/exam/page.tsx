'use client'
import { useEffect, useRef, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'

interface RiskEvent {
  type: string
  severity: 'low' | 'medium' | 'high'
  timestamp: string
  message: string
}

const QUESTIONS = [
  {
    id: 1,
    text: 'Мэдээллийн системийн үндсэн бүрэлдэхүүн хэсгүүдийг тодорхойл.',
    type: 'text',
  },
  {
    id: 2,
    text: 'Өгөгдлийн сангийн нормализацийн зорилго юу вэ?',
    type: 'choice',
    options: [
      'Өгөгдлийн давхардлыг арилгах',
      'Хурдыг нэмэгдүүлэх',
      'Хадгалах зайг ихэсгэх',
      'Нууцлалыг сайжруулах',
    ],
  },
  {
    id: 3,
    text: 'REST болон SOAP архитектурыг харьцуул.',
    type: 'text',
  },
]

export default function ExamPage() {
  const router   = useRouter()
  const videoRef = useRef<HTMLVideoElement>(null)
  const wsRef    = useRef<WebSocket | null>(null)
  const streamRef = useRef<MediaStream | null>(null)

  const [timeLeft, setTimeLeft]   = useState(50 * 60)
  const [warning, setWarning]     = useState<string | null>(null)
  const [answers, setAnswers]     = useState<Record<number, string>>({})
  const [current, setCurrent]     = useState(0)
  const [flagCount, setFlagCount] = useState(0)

  // ── Камер ──
  useEffect(() => {
    navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: true })
      .then(stream => {
        streamRef.current = stream
        if (videoRef.current) videoRef.current.srcObject = stream
        connectWS()
      })
      .catch(() => router.push('/'))
  }, [])

  // ── WebSocket ──
  const connectWS = useCallback(() => {
    const studentId = 'student_001' // жинхэнэд нь session-аас авна
    const ws = new WebSocket(`${process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'}/ws/student/${studentId}`)
    ws.onopen    = () => console.log('[WS] Холбогдсон')
    ws.onmessage = (e) => {
      const data: RiskEvent = JSON.parse(e.data)
      setFlagCount(p => p + 1)
      setWarning(data.message)
      setTimeout(() => setWarning(null), 5000)
    }
    ws.onclose = () => setTimeout(connectWS, 3000) // auto-reconnect
    wsRef.current = ws
  }, [])

  // ── Фрейм илгээх ──
  useEffect(() => {
    const canvas   = document.createElement('canvas')
    const interval = setInterval(() => {
      const video = videoRef.current
      if (!video || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
      canvas.width  = video.videoWidth  || 640
      canvas.height = video.videoHeight || 480
      canvas.getContext('2d')?.drawImage(video, 0, 0)
      canvas.toBlob(blob => {
        if (blob && wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(blob)
      }, 'image/jpeg', 0.6)
    }, 1000)
    return () => clearInterval(interval)
  }, [])

  // ── Tab switch ──
  useEffect(() => {
    const handler = () => {
      if (document.hidden && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ event: 'tab_switch', timestamp: new Date().toISOString() }))
      }
    }
    document.addEventListener('visibilitychange', handler)
    return () => document.removeEventListener('visibilitychange', handler)
  }, [])

  // ── Copy/paste хориглох ──
  useEffect(() => {
    const block = (e: Event) => { e.preventDefault() }
    document.addEventListener('copy', block)
    document.addEventListener('paste', block)
    document.addEventListener('contextmenu', block)
    return () => {
      document.removeEventListener('copy', block)
      document.removeEventListener('paste', block)
      document.removeEventListener('contextmenu', block)
    }
  }, [])

  // ── Тоолуур ──
  useEffect(() => {
    const t = setInterval(() => {
      setTimeLeft(p => {
        if (p <= 1) { handleSubmit(); return 0 }
        return p - 1
      })
    }, 1000)
    return () => clearInterval(t)
  }, [])

  const handleSubmit = () => {
    streamRef.current?.getTracks().forEach(t => t.stop())
    wsRef.current?.close()
    router.push('/done')
  }

  const fmt = (s: number) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
  const q   = QUESTIONS[current]

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col select-none">

      {/* Topbar */}
      <div className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between sticky top-0 z-10">
        <div>
          <div className="font-semibold text-gray-900">Мэдээллийн систем — Улирлын шалгалт</div>
          <div className="text-xs text-gray-500">СЭЗИС · МСМ тэнхим</div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-center">
            <div className={`text-2xl font-bold tabular-nums ${timeLeft < 300 ? 'text-red-600 animate-pulse' : 'text-gray-900'}`}>
              {fmt(timeLeft)}
            </div>
            <div className="text-xs text-gray-400">үлдсэн</div>
          </div>
          <button
            onClick={() => { if (confirm('Шалгалтыг илгээхэд бэлэн үү?')) handleSubmit() }}
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-2 rounded-lg"
          >
            Илгээх
          </button>
        </div>
      </div>

      {/* Warning banner */}
      {warning && (
        <div className="bg-yellow-50 border-l-4 border-yellow-500 px-6 py-3 flex items-center gap-2 text-yellow-800 font-medium text-sm">
          <span>⚠</span> {warning}
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">

        {/* Асуулт хэсэг */}
        <div className="flex-1 overflow-y-auto p-6">

          {/* Progress */}
          <div className="flex items-center gap-2 mb-6">
            {QUESTIONS.map((_, i) => (
              <button
                key={i}
                onClick={() => setCurrent(i)}
                className={`w-8 h-8 rounded-full text-sm font-semibold transition-colors
                  ${i === current ? 'bg-blue-600 text-white' : answers[QUESTIONS[i].id] ? 'bg-green-100 text-green-700 border border-green-300' : 'bg-gray-100 text-gray-500'}`}
              >
                {i + 1}
              </button>
            ))}
            <span className="text-xs text-gray-400 ml-2">{Object.keys(answers).length}/{QUESTIONS.length} хариулсан</span>
          </div>

          {/* Question card */}
          <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
            <div className="text-xs font-semibold text-blue-600 mb-3">АСУУЛТ {current + 1}</div>
            <p className="text-gray-900 font-medium mb-5">{q.text}</p>

            {q.type === 'text' ? (
              <textarea
                value={answers[q.id] || ''}
                onChange={e => setAnswers(p => ({ ...p, [q.id]: e.target.value }))}
                placeholder="Хариултаа бичнэ үү..."
                rows={6}
                className="w-full border border-gray-200 rounded-lg p-3 text-sm resize-none focus:outline-none focus:border-blue-400"
              />
            ) : (
              <div className="space-y-2">
                {q.options?.map((opt, i) => (
                  <label key={i} className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 cursor-pointer hover:bg-gray-50">
                    <input
                      type="radio"
                      name={`q${q.id}`}
                      value={opt}
                      checked={answers[q.id] === opt}
                      onChange={() => setAnswers(p => ({ ...p, [q.id]: opt }))}
                      className="w-4 h-4 text-blue-600"
                    />
                    <span className="text-sm text-gray-700">{opt}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          {/* Nav */}
          <div className="flex justify-between">
            <button
              onClick={() => setCurrent(p => Math.max(0, p - 1))}
              disabled={current === 0}
              className="px-4 py-2 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
            >← Өмнөх</button>
            <button
              onClick={() => setCurrent(p => Math.min(QUESTIONS.length - 1, p + 1))}
              disabled={current === QUESTIONS.length - 1}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg disabled:opacity-40 hover:bg-blue-700"
            >Дараах →</button>
          </div>
        </div>

        {/* Камерын хэсэг */}
        <div className="w-56 bg-white border-l border-gray-200 p-4 flex flex-col gap-4">
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Таны камер</div>
          <div className="relative bg-black rounded-xl overflow-hidden aspect-video">
            <video ref={videoRef} autoPlay muted playsInline className="w-full h-full object-cover" />
            <div className="absolute top-2 left-2 flex items-center gap-1">
              <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              <span className="text-white text-xs">REC</span>
            </div>
          </div>
          <div className="text-xs text-gray-400 bg-gray-50 rounded-lg p-3 leading-5">
            📹 Шалгалтын бичлэг хадгалагдаж байна.<br />
            Камерийн өмнө байрлана уу.
          </div>
          {flagCount > 0 && (
            <div className="text-xs text-yellow-700 bg-yellow-50 rounded-lg p-3">
              ⚠ {flagCount} анхааруулга бүртгэгдсэн
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
