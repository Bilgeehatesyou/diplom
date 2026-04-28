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

function formatTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

export default function ExamPage() {
  const router = useRouter()
  const videoRef = useRef<HTMLVideoElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const canvasRef = useRef<HTMLCanvasElement>(document.createElement('canvas'))
  const frameIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [timeLeft, setTimeLeft] = useState(50 * 60)
  const [warning, setWarning] = useState<string | null>(null)
  const [answers, setAnswers] = useState<Record<number, string>>({})
  const [current, setCurrent] = useState(0)
  const [flagCount, setFlagCount] = useState(0)
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')

  // Initialize camera and WebSocket
  useEffect(() => {
    navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: false })
      .then(stream => {
        streamRef.current = stream
        if (videoRef.current) videoRef.current.srcObject = stream
        initWS()
      })
      .catch(() => router.push('/'))

    return () => {
      streamRef.current?.getTracks().forEach(t => t.stop())
      wsRef.current?.close()
      if (frameIntervalRef.current) clearInterval(frameIntervalRef.current)
    }
  }, [])

  const initWS = useCallback(() => {
    const studentId = 'student_001'
    const ws = new WebSocket(`${process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'}/ws/student/${studentId}`)

    ws.onopen = () => setWsStatus('connected')
    ws.onclose = () => {
      setWsStatus('disconnected')
      setTimeout(initWS, 3000)
    }
    ws.onerror = () => setWsStatus('disconnected')

    ws.onmessage = (e) => {
      const data: RiskEvent = JSON.parse(e.data)
      setFlagCount(p => p + 1)
      setWarning(data.message)
      setTimeout(() => setWarning(null), 4000)
    }

    wsRef.current = ws

    // Start sending frames
    frameIntervalRef.current = setInterval(() => {
      const video = videoRef.current
      const ws = wsRef.current
      if (!video || !ws || ws.readyState !== WebSocket.OPEN) return

      const canvas = canvasRef.current
      canvas.width = video.videoWidth || 640
      canvas.height = video.videoHeight || 480
      canvas.getContext('2d')?.drawImage(video, 0, 0)
      canvas.toBlob(blob => {
        if (blob && wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(blob)
        }
      }, 'image/jpeg', 0.5)
    }, 1000)
  }, [])

  // Tab switch detection
  useEffect(() => {
    const handler = () => {
      if (document.hidden && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          event: 'tab_switch',
          timestamp: new Date().toISOString(),
        }))
      }
    }
    document.addEventListener('visibilitychange', handler)
    return () => document.removeEventListener('visibilitychange', handler)
  }, [])

  // Copy/paste/context block
  useEffect(() => {
    const block = (e: Event) => e.preventDefault()
    document.addEventListener('copy', block)
    document.addEventListener('paste', block)
    document.addEventListener('contextmenu', block)
    return () => {
      document.removeEventListener('copy', block)
      document.removeEventListener('paste', block)
      document.removeEventListener('contextmenu', block)
    }
  }, [])

  // Countdown timer
  useEffect(() => {
    const t = setInterval(() => {
      setTimeLeft(p => {
        if (p <= 1) {
          handleSubmit()
          return 0
        }
        return p - 1
      })
    }, 1000)
    return () => clearInterval(t)
  }, [])

  const handleSubmit = () => {
    streamRef.current?.getTracks().forEach(t => t.stop())
    wsRef.current?.close()
    if (frameIntervalRef.current) clearInterval(frameIntervalRef.current)
    router.push('/done')
  }

  const q = QUESTIONS[current]
  const answeredCount = Object.keys(answers).length

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">

      {/* ── Fixed Warning Banner ── */}
      {warning && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-red-50 border-b-2 border-red-300 px-5 py-3 flex items-center gap-3 shadow-md">
          <span className="text-red-600 text-lg font-bold">⚠</span>
          <span className="text-sm text-red-700 font-medium">{warning}</span>
        </div>
      )}

      {/* ── Header ── */}
      <header className={`bg-white border-b border-slate-200 px-5 py-3 flex items-center justify-between shadow-sm ${warning ? 'mt-12' : ''}`}>
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 bg-blue-600 rounded flex items-center justify-center">
            <span className="text-white text-xs font-bold">AP</span>
          </div>
          <div>
            <div className="text-sm font-medium text-slate-800 leading-none">Мэдээллийн систем</div>
            <div className="text-xs text-slate-400 mt-0.5">Улирлын шалгалт · СЭЗИС</div>
          </div>
        </div>

        <div className="flex items-center gap-5">
          {/* Camera status */}
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${streamRef.current ? 'bg-emerald-500' : 'bg-red-400 animate-pulse'}`} />
            <span className="text-xs text-slate-500">Камер {streamRef.current ? 'идэвхтэй' : 'алдаа'}</span>
          </div>

          {/* WS status */}
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${
              wsStatus === 'connected' ? 'bg-emerald-500' :
              wsStatus === 'connecting' ? 'bg-amber-400 animate-pulse' : 'bg-red-400'
            }`} />
            <span className="text-xs text-slate-500">
              {wsStatus === 'connected' ? 'Холбогдсон' : wsStatus === 'connecting' ? 'Холбогдож байна...' : 'Алдсан'}
            </span>
          </div>

          {/* Timer */}
          <div className="flex items-center gap-2 border-l border-slate-200 pl-5">
            <div className="text-right">
              <div className={`text-xl font-bold tabular-nums font-mono ${
                timeLeft < 300 ? 'text-red-600' : 'text-slate-800'
              }`}>
                {formatTime(timeLeft)}
              </div>
              <div className="text-xs text-slate-400 leading-none">Үлдсэн</div>
            </div>
          </div>

          {/* Submit */}
          <button
            onClick={() => { if (confirm('Шалгалтыг илгээх үү?')) handleSubmit() }}
            className="px-4 py-1.5 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 transition-colors"
          >
            Илгээх
          </button>
        </div>
      </header>

      {/* ── Content ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* Question Panel */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-3xl mx-auto">

            {/* Progress bar */}
            <div className="flex items-center gap-3 mb-6">
              <div className="flex gap-2">
                {QUESTIONS.map((_, i) => (
                  <button
                    key={i}
                    onClick={() => setCurrent(i)}
                    className={`w-8 h-8 rounded text-sm font-medium transition-colors ${
                      i === current
                        ? 'bg-blue-600 text-white'
                        : answers[QUESTIONS[i].id]
                          ? 'bg-emerald-100 text-emerald-700 border border-emerald-200'
                          : 'bg-slate-100 text-slate-500'
                    }`}
                  >
                    {i + 1}
                  </button>
                ))}
              </div>
              <span className="text-sm text-slate-400">{answeredCount}/{QUESTIONS.length} хариулсан</span>
            </div>

            {/* Question card */}
            <div className="bg-white rounded-xl border border-slate-200 p-6 mb-5">
              <div className="text-sm font-bold text-blue-600 uppercase tracking-wider mb-4">
                Асуулт {current + 1}
              </div>
              <p className="text-base text-slate-800 font-medium leading-relaxed mb-6">
                {q.text}
              </p>

              {q.type === 'text' ? (
                <textarea
                  value={answers[q.id] || ''}
                  onChange={e => setAnswers(p => ({ ...p, [q.id]: e.target.value }))}
                  placeholder="Хариултаа энд бичнэ үү..."
                  rows={8}
                  className="w-full border-2 border-slate-200 rounded-xl p-4 text-base text-slate-800 resize-none focus:outline-none focus:border-blue-400 placeholder-slate-300"
                />
              ) : (
                <div className="space-y-3">
                  {q.options?.map((opt, i) => (
                    <label
                      key={i}
                      className="flex items-center gap-4 p-4 rounded-xl border-2 border-slate-200 cursor-pointer hover:bg-slate-50 transition-colors"
                    >
                      <input
                        type="radio"
                        name={`q${q.id}`}
                        value={opt}
                        checked={answers[q.id] === opt}
                        onChange={() => setAnswers(p => ({ ...p, [q.id]: opt }))}
                        className="w-5 h-5 text-blue-600 border-slate-300"
                      />
                      <span className="text-base text-slate-700">{opt}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            {/* Navigation */}
            <div className="flex justify-between items-center">
              <button
                onClick={() => setCurrent(p => Math.max(0, p - 1))}
                disabled={current === 0}
                className="px-5 py-2.5 text-sm border-2 border-slate-200 rounded-xl text-slate-600 hover:bg-slate-50 disabled:opacity-35 disabled:cursor-not-allowed transition-colors"
              >
                ← Өмнөх
              </button>
              <div className="text-sm text-slate-400">
                {current + 1} / {QUESTIONS.length}
              </div>
              <button
                onClick={() => setCurrent(p => Math.min(QUESTIONS.length - 1, p + 1))}
                disabled={current === QUESTIONS.length - 1}
                className="px-5 py-2.5 text-sm bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-35 disabled:cursor-not-allowed transition-colors"
              >
                Дараах →
              </button>
            </div>
          </div>
        </div>

        {/* Camera Sidebar */}
        <div className="w-64 bg-white border-l border-slate-200 flex flex-col p-5 gap-4">
          <div className="text-sm font-bold text-slate-400 uppercase tracking-wider">
            Таны камер
          </div>
          <div className="relative bg-black rounded-xl overflow-hidden aspect-video">
            <video
              ref={videoRef}
              autoPlay
              muted
              playsInline
              className="w-full h-full object-cover"
            />
            {streamRef.current && (
              <div className="absolute top-2 left-2 flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
                <span className="text-white text-xs font-medium">REC</span>
              </div>
            )}
          </div>

          <div className="bg-slate-50 rounded-xl p-4">
            <p className="text-sm text-slate-500 leading-relaxed">
              Шалгалтын бичлэг хадгалагдаж байна
            </p>
          </div>

          {flagCount > 0 && (
            <div className="bg-red-50 border-2 border-red-200 rounded-xl p-4">
              <p className="text-sm text-red-600 font-bold">
                {flagCount} анхааруулга бүртгэгдсэн
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}