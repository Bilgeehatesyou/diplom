'use client'
import { useEffect, useRef, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { WS, apiFetch, ApiError, getStudent, clearStudent, StudentAuth } from '../../lib/api'

interface Question {
  id: number
  text: string
  type: 'text' | 'choice'
  options?: string[]
}

interface ExamInfo {
  exam_id: string
  title: string
  duration_sec: number
  questions: Question[]
}

interface StartResponse {
  session_id: number
  remaining_sec: number
  answers: Record<string, string>
  flag_count: number
  exam: ExamInfo
}

const EXAM_ID = 'exam_001'
const FRAME_INTERVAL_MS = 200          // 5 fps — сервер 1 Hz шинжилдэг, багшийн preview-д хангалттай
const FRAME_WIDTH = 640                // 1280×720 → 640×360 (upload ~4 дахин бага)
const MAX_WS_BUFFER = 1_000_000        // удаан сүлжээнд кадр хуримтлуулахгүй
const AUTOSAVE_DEBOUNCE_MS = 1500
const AUTOSAVE_INTERVAL_MS = 30_000
const VIRTUAL_CAM_RE = /obs|virtual|manycam|snap camera|xsplit|droidcam|camo|splitcam|youcam|e2esoft/i

type ClientEvent =
  | 'tab_switch' | 'fullscreen_exit' | 'focus_lost' | 'copy_attempt'
  | 'mic_denied' | 'mic_ended' | 'camera_ended' | 'virtual_camera'

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
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const frameIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const closingRef = useRef(false)                 // илгээсэн/гарч байгаа → reconnect хийхгүй
  const submittingRef = useRef(false)
  const confirmOpenRef = useRef(false)
  const frameInFlightRef = useRef(false)
  const pendingEventsRef = useRef<{ event: ClientEvent; detail?: string }[]>([])
  const sessionIdRef = useRef<number | null>(null)
  const answersRef = useRef<Record<string, string>>({})
  const dirtyRef = useRef(false)
  const savingRef = useRef(false)
  const endAtRef = useRef<number>(0)

  const [student, setStudentState] = useState<StudentAuth | null>(null)
  const [exam, setExam] = useState<ExamInfo | null>(null)
  const [timeLeft, setTimeLeft] = useState(0)
  const [warning, setWarning] = useState<string | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [current, setCurrent] = useState(0)
  const [flagCount, setFlagCount] = useState(0)
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')
  const [cameraOk, setCameraOk] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [isFullscreen, setIsFullscreen] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // ── Event мэдээлэх (WS холбогдоогүй үед дараалалд хадгална) ──
  const sendEvent = useCallback((event: ClientEvent, detail?: string) => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ event, detail, timestamp: new Date().toISOString() }))
    } else if (!pendingEventsRef.current.some(p => p.event === event)) {
      pendingEventsRef.current.push({ event, detail })
    }
  }, [])

  const stopRecorder = () => {
    const rec = mediaRecorderRef.current
    if (rec && rec.state !== 'inactive') {
      try { rec.stop() } catch {}
    }
    mediaRecorderRef.current = null
  }

  // Шинэ WS холболт бүрд recorder-ийг дахин эхлүүлнэ → эхний chunk нь EBML header-тэй
  const startRecorder = () => {
    stopRecorder()
    const audioTracks = streamRef.current?.getAudioTracks().filter(t => t.readyState === 'live') ?? []
    if (audioTracks.length === 0) return
    try {
      const audioOnly = new MediaStream(audioTracks)
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : ''
      const recorder = mimeType ? new MediaRecorder(audioOnly, { mimeType }) : new MediaRecorder(audioOnly)
      mediaRecorderRef.current = recorder
      recorder.ondataavailable = async (e) => {
        if (!e.data || e.data.size === 0) return
        const buf = await e.data.arrayBuffer()
        const ws = wsRef.current
        if (ws?.readyState === WebSocket.OPEN && recorder === mediaRecorderRef.current) {
          ws.send(JSON.stringify({ _audio: true }))
          ws.send(buf)
        }
      }
      recorder.start(2000)
    } catch (err) {
      console.error('[Audio] recorder error:', err)
    }
  }

  // ── Бүх зүйлийг зогсоогоод шилжих ──
  const finish = useCallback((path: string) => {
    closingRef.current = true
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    if (frameIntervalRef.current) clearInterval(frameIntervalRef.current)
    stopRecorder()
    try { wsRef.current?.close(1000, 'finished') } catch {}
    streamRef.current?.getTracks().forEach(t => t.stop())
    if (sessionIdRef.current) localStorage.removeItem(`ap_draft_${sessionIdRef.current}`)
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
    router.replace(path)
  }, [router])

  const handleAuthLost = useCallback(() => {
    closingRef.current = true
    clearStudent()
    finish('/login')
  }, [finish])

  // ── WebSocket ──
  const initWS = useCallback(() => {
    if (closingRef.current) return
    const s = getStudent()
    if (!s) { handleAuthLost(); return }
    setWsStatus('connecting')
    const ws = new WebSocket(`${WS}/ws/student?exam_id=${EXAM_ID}`)
    wsRef.current = ws

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'auth', token: s.token }))   // token URL-д биш
    }

    ws.onmessage = (e) => {
      let data: any
      try { data = JSON.parse(e.data) } catch { return }
      if (data.type === 'ready') {
        setWsStatus('connected')
        for (const p of pendingEventsRef.current.splice(0)) {
          ws.send(JSON.stringify({ ...p, timestamp: new Date().toISOString() }))
        }
        startRecorder()
      } else if (data.type === 'event') {
        setFlagCount(p => p + 1)
        setWarning(data.message)
        setTimeout(() => setWarning(null), 4000)
      } else if (data.type === 'exam_ended') {
        finish('/done?r=time')
      } else if (data.type === 'replaced') {
        closingRef.current = true
        setNotice('Шалгалт өөр цонх/tab-д нээгдсэн тул энэ цонхны хяналт зогслоо.')
      }
    }

    ws.onclose = (e) => {
      if (wsRef.current === ws) stopRecorder()
      setWsStatus('disconnected')
      if (closingRef.current || wsRef.current !== ws) return
      if (e.code === 4401) { handleAuthLost(); return }
      if (e.code === 4409) { finish('/done?r=ended'); return }
      if (e.code === 4000) {
        closingRef.current = true
        setNotice('Шалгалт өөр цонх/tab-д нээгдсэн тул энэ цонхны хяналт зогслоо.')
        return
      }
      reconnectTimerRef.current = setTimeout(initWS, 3000)
    }
  }, [finish, handleAuthLost])

  // ── Камер/микрофон ──
  const startMedia = useCallback(async () => {
    let stream: MediaStream | null = null
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: true,
      })
    } catch {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
        sendEvent('mic_denied')
      } catch {
        stream = null
      }
    }
    if (closingRef.current) { stream?.getTracks().forEach(t => t.stop()); return }
    if (!stream) {
      setCameraOk(false)
      setLoadError('Камер ашиглах боломжгүй байна. Browser-ийн зөвшөөрлийг шалгаад хуудсыг дахин ачаална уу.')
      sendEvent('camera_ended', 'getUserMedia failed')
      initWS()   // камергүй ч холбогдоно → сервер зөрчлийг бүртгэж, багш онлайн байдлыг харна
      return
    }
    streamRef.current = stream
    if (videoRef.current) videoRef.current.srcObject = stream
    setCameraOk(true)

    const vTrack = stream.getVideoTracks()[0]
    if (vTrack) {
      if (VIRTUAL_CAM_RE.test(vTrack.label)) sendEvent('virtual_camera', vTrack.label)
      vTrack.addEventListener('ended', () => {
        setCameraOk(false)
        if (!closingRef.current) sendEvent('camera_ended')
      })
    }
    stream.getAudioTracks().forEach(t => t.addEventListener('ended', () => {
      if (!closingRef.current) sendEvent('mic_ended')
    }))

    if (frameIntervalRef.current) clearInterval(frameIntervalRef.current)
    frameIntervalRef.current = setInterval(() => {
      const video = videoRef.current
      const ws = wsRef.current
      if (!video || !ws || ws.readyState !== WebSocket.OPEN || frameInFlightRef.current) return
      if (ws.bufferedAmount > MAX_WS_BUFFER || !video.videoWidth) return
      if (!canvasRef.current) canvasRef.current = document.createElement('canvas')
      const canvas = canvasRef.current
      canvas.width = FRAME_WIDTH
      canvas.height = Math.round(FRAME_WIDTH * video.videoHeight / video.videoWidth)
      canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height)
      frameInFlightRef.current = true
      canvas.toBlob(blob => {
        frameInFlightRef.current = false
        if (blob && wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(blob)
      }, 'image/jpeg', 0.7)
    }, FRAME_INTERVAL_MS)

    initWS()
  }, [initWS, sendEvent])

  // ── Эхлэл: серверээс шалгалт/хугацаа/хадгалсан хариулт авах ──
  useEffect(() => {
    closingRef.current = false
    const s = getStudent()
    if (!s) { router.replace('/login'); return }
    setStudentState(s)
    let cancelled = false

    ;(async () => {
      let data: StartResponse
      try {
        data = await apiFetch<StartResponse>('/api/exam/start', {
          method: 'POST', body: JSON.stringify({ exam_id: EXAM_ID }),
        })
      } catch (e) {
        if (cancelled) return
        if (e instanceof ApiError && e.status === 401) { clearStudent(); router.replace('/login'); return }
        if (e instanceof ApiError && e.code === 'already_submitted') { router.replace('/done?r=already'); return }
        setLoadError(e instanceof Error ? e.message : 'Шалгалт ачаалахад алдаа гарлаа')
        return
      }
      if (cancelled) return

      sessionIdRef.current = data.session_id
      endAtRef.current = Date.now() + data.remaining_sec * 1000
      setTimeLeft(data.remaining_sec)
      setExam(data.exam)
      setFlagCount(data.flag_count || 0)

      // Сервер = эх сурвалж. Сүлжээ тасарч autosave амжаагүй бол local draft-ийг сэргээнэ.
      let initial = data.answers || {}
      try {
        const cached = JSON.parse(localStorage.getItem(`ap_draft_${data.session_id}`) || 'null')
        if (cached && cached.synced === false && cached.answers) {
          initial = cached.answers
          dirtyRef.current = true
        }
      } catch {}
      answersRef.current = initial
      setAnswers(initial)

      startMedia()
    })()

    return () => {
      cancelled = true
      closingRef.current = true
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      if (frameIntervalRef.current) clearInterval(frameIntervalRef.current)
      stopRecorder()
      try { wsRef.current?.close(1000, 'unmount') } catch {}
      streamRef.current?.getTracks().forEach(t => t.stop())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Autosave ──
  const saveNow = useCallback(async () => {
    if (!dirtyRef.current || savingRef.current || closingRef.current) return
    savingRef.current = true
    dirtyRef.current = false
    const snapshot = answersRef.current
    setSaveStatus('saving')
    try {
      await apiFetch('/api/exam/answers', {
        method: 'PUT', body: JSON.stringify({ exam_id: EXAM_ID, answers: snapshot }),
      })
      if (sessionIdRef.current && answersRef.current === snapshot) {
        localStorage.setItem(`ap_draft_${sessionIdRef.current}`, JSON.stringify({ answers: snapshot, synced: true }))
      }
      setSaveStatus('saved')
    } catch (e) {
      dirtyRef.current = true
      setSaveStatus('error')
      if (e instanceof ApiError && e.status === 401) handleAuthLost()
      else if (e instanceof ApiError && e.status === 409) finish('/done?r=time')
    } finally {
      savingRef.current = false
    }
  }, [finish, handleAuthLost])

  const updateAnswer = (qid: number, value: string) => {
    setAnswers(prev => {
      const next = { ...prev, [String(qid)]: value }
      answersRef.current = next
      dirtyRef.current = true
      if (sessionIdRef.current) {
        localStorage.setItem(`ap_draft_${sessionIdRef.current}`, JSON.stringify({ answers: next, synced: false }))
      }
      return next
    })
  }

  useEffect(() => {
    if (!exam) return
    const t = setTimeout(saveNow, AUTOSAVE_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [answers, exam, saveNow])

  useEffect(() => {
    const t = setInterval(saveNow, AUTOSAVE_INTERVAL_MS)
    return () => clearInterval(t)
  }, [saveNow])

  // ── Илгээх ──
  const handleSubmit = useCallback(async () => {
    if (submittingRef.current) return
    submittingRef.current = true
    setSubmitting(true)
    setSubmitError(null)
    try {
      await apiFetch('/api/exam/submit', {
        method: 'POST', body: JSON.stringify({ exam_id: EXAM_ID, answers: answersRef.current }),
      })
      finish('/done')
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { handleAuthLost(); return }
      if (e instanceof ApiError && e.code === 'time_over') { finish('/done?r=time'); return }
      if (e instanceof ApiError && e.code === 'no_active_session') { finish('/done?r=ended'); return }
      submittingRef.current = false
      setSubmitting(false)
      setSubmitError(`${e instanceof Error ? e.message : 'Алдаа'} — хариулт хадгалагдсан, дахин илгээнэ үү.`)
    }
  }, [finish, handleAuthLost])

  // ── Таймер (серверийн үлдсэн хугацаанаас) ──
  useEffect(() => {
    if (!exam) return
    const t = setInterval(() => {
      const left = Math.max(0, Math.ceil((endAtRef.current - Date.now()) / 1000))
      setTimeLeft(left)
      if (left <= 0) handleSubmit()
    }, 1000)
    return () => clearInterval(t)
  }, [exam, handleSubmit])

  // ── Хуулах оролдлогын хяналт ──
  useEffect(() => {
    const onVisibility = () => { if (document.hidden && !closingRef.current) sendEvent('tab_switch') }
    const onBlur = () => {
      setTimeout(() => {
        if (closingRef.current || confirmOpenRef.current || document.hidden || document.hasFocus()) return
        sendEvent('focus_lost')   // өөр дэлгэц/цонх руу шилжсэн (tab солих биш)
      }, 300)
    }
    const onCopy = (e: ClipboardEvent) => { e.preventDefault(); sendEvent('copy_attempt', e.type) }
    const onContext = (e: Event) => e.preventDefault()
    const onFullscreen = () => {
      const fs = !!document.fullscreenElement
      setIsFullscreen(fs)
      if (!fs && !closingRef.current) sendEvent('fullscreen_exit')
    }
    setIsFullscreen(!document.fullscreenEnabled || !!document.fullscreenElement)

    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('blur', onBlur)
    document.addEventListener('copy', onCopy)
    document.addEventListener('cut', onCopy)
    document.addEventListener('paste', onCopy)
    document.addEventListener('contextmenu', onContext)
    document.addEventListener('fullscreenchange', onFullscreen)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('blur', onBlur)
      document.removeEventListener('copy', onCopy)
      document.removeEventListener('cut', onCopy)
      document.removeEventListener('paste', onCopy)
      document.removeEventListener('contextmenu', onContext)
      document.removeEventListener('fullscreenchange', onFullscreen)
    }
  }, [sendEvent])

  const enterFullscreen = () => {
    document.documentElement.requestFullscreen?.().catch(() => {})
  }

  const confirmSubmit = () => {
    confirmOpenRef.current = true
    const ok = confirm('Шалгалтыг илгээх үү? Илгээсний дараа засах боломжгүй.')
    confirmOpenRef.current = false
    if (ok) handleSubmit()
  }

  if (loadError && !exam) {
    return (
      <div className="flex items-center justify-center min-h-screen p-6 bg-slate-50">
        <div className="max-w-sm p-8 text-center bg-white border rounded-xl border-slate-200">
          <p className="mb-4 text-sm text-red-700">{loadError}</p>
          <button onClick={() => location.reload()}
                  className="px-4 py-2 text-sm text-white bg-blue-600 rounded hover:bg-blue-700">Дахин оролдох</button>
        </div>
      </div>
    )
  }

  if (!exam) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-50">
        <div className="w-8 h-8 border-2 rounded-full border-slate-300 border-t-blue-600 animate-spin" />
      </div>
    )
  }

  const questions = exam.questions
  const q = questions[current]
  const answeredCount = questions.filter(x => (answers[String(x.id)] || '').trim()).length

  return (
    <div className="flex flex-col min-h-screen bg-slate-50">

      {/* ── Fullscreen шаардлага ── */}
      {!isFullscreen && !notice && (
        <div className="fixed inset-0 z-40 flex items-center justify-center p-6 bg-slate-900/80 backdrop-blur-sm">
          <div className="max-w-sm p-6 text-center bg-white rounded-xl">
            <p className="mb-1 text-sm font-semibold text-slate-800">Шалгалтыг бүтэн дэлгэцээр өгнө</p>
            <p className="mb-4 text-xs text-slate-500">Бүтэн дэлгэцээс гарах бүр багшид бүртгэгдэнэ. Үргэлжлүүлэхийн тулд бүтэн дэлгэц рүү орно уу.</p>
            <button onClick={enterFullscreen}
                    className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700">
              Бүтэн дэлгэц рүү орох
            </button>
          </div>
        </div>
      )}

      {notice && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-slate-900/80">
          <div className="max-w-sm p-6 text-center bg-white rounded-xl">
            <p className="text-sm text-slate-700">{notice}</p>
          </div>
        </div>
      )}

      {/* ── Fixed Warning Banner ── */}
      {warning && (
        <div className="fixed top-0 left-0 right-0 z-50 flex items-center gap-3 px-5 py-3 border-b-2 border-red-300 shadow-md bg-red-50">
          <span className="text-lg font-bold text-red-600">⚠</span>
          <span className="text-sm font-medium text-red-700">{warning}</span>
        </div>
      )}

      {/* ── Header ── */}
      <header className={`bg-white border-b border-slate-200 px-5 py-3 flex items-center justify-between shadow-sm ${warning ? 'mt-12' : ''}`}>
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center bg-blue-600 rounded w-7 h-7">
            <span className="text-xs font-bold text-white">AP</span>
          </div>
          <div>
            <div className="text-sm font-medium leading-none text-slate-800">{exam.title}</div>
            <div className="text-xs text-slate-400 mt-0.5">
              {student ? `${student.name} · ${student.student_id}` : 'СЭЗИС'}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-5">
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${cameraOk ? 'bg-emerald-500' : 'bg-red-400 animate-pulse'}`} />
            <span className="text-xs text-slate-500">Камер {cameraOk ? 'идэвхтэй' : 'алдаа'}</span>
          </div>

          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${
              wsStatus === 'connected' ? 'bg-emerald-500' :
              wsStatus === 'connecting' ? 'bg-amber-400 animate-pulse' : 'bg-red-400'
            }`} />
            <span className="text-xs text-slate-500">
              {wsStatus === 'connected' ? 'Холбогдсон' : wsStatus === 'connecting' ? 'Холбогдож байна...' : 'Алдсан'}
            </span>
          </div>

          <div className="text-xs text-slate-400 min-w-[90px]">
            {saveStatus === 'saving' ? 'Хадгалж байна…' :
             saveStatus === 'saved' ? '✓ Хадгалагдсан' :
             saveStatus === 'error' ? <span className="text-red-500">Хадгалж чадсангүй</span> : ''}
          </div>

          <div className="flex items-center gap-2 pl-5 border-l border-slate-200">
            <div className="text-right">
              <div className={`text-xl font-bold tabular-nums font-mono ${timeLeft < 300 ? 'text-red-600' : 'text-slate-800'}`}>
                {formatTime(timeLeft)}
              </div>
              <div className="text-xs leading-none text-slate-400">Үлдсэн</div>
            </div>
          </div>

          <button
            onClick={confirmSubmit}
            disabled={submitting}
            className="px-4 py-1.5 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-60 transition-colors"
          >
            {submitting ? 'Илгээж байна…' : 'Илгээх'}
          </button>
        </div>
      </header>

      {(submitError || loadError) && (
        <div className="px-5 py-2 text-sm text-red-700 border-b border-red-200 bg-red-50">{submitError || loadError}</div>
      )}

      {/* ── Content ── */}
      <div className="flex flex-1 overflow-hidden">

        <div className="flex-1 p-6 overflow-y-auto">
          <div className="max-w-3xl mx-auto">

            <div className="flex items-center gap-3 mb-6">
              <div className="flex gap-2">
                {questions.map((qq, i) => (
                  <button
                    key={qq.id}
                    onClick={() => setCurrent(i)}
                    className={`w-8 h-8 rounded text-sm font-medium transition-colors ${
                      i === current
                        ? 'bg-blue-600 text-white'
                        : (answers[String(qq.id)] || '').trim()
                          ? 'bg-emerald-100 text-emerald-700 border border-emerald-200'
                          : 'bg-slate-100 text-slate-500'
                    }`}
                  >
                    {i + 1}
                  </button>
                ))}
              </div>
              <span className="text-sm text-slate-400">{answeredCount}/{questions.length} хариулсан</span>
            </div>

            <div className="p-6 mb-5 bg-white border rounded-xl border-slate-200">
              <div className="mb-4 text-sm font-bold tracking-wider text-blue-600 uppercase">
                Асуулт {current + 1}
              </div>
              <p className="mb-6 text-base font-medium leading-relaxed text-slate-800">{q.text}</p>

              {q.type === 'text' ? (
                <textarea
                  value={answers[String(q.id)] || ''}
                  onChange={e => updateAnswer(q.id, e.target.value)}
                  placeholder="Хариултаа энд бичнэ үү..."
                  rows={8}
                  className="w-full p-4 text-base border-2 resize-none border-slate-200 rounded-xl text-slate-800 focus:outline-none focus:border-blue-400 placeholder-slate-300"
                />
              ) : (
                <div className="space-y-3">
                  {q.options?.map((opt, i) => (
                    <label
                      key={i}
                      className="flex items-center gap-4 p-4 transition-colors border-2 cursor-pointer rounded-xl border-slate-200 hover:bg-slate-50"
                    >
                      <input
                        type="radio"
                        name={`q${q.id}`}
                        value={opt}
                        checked={answers[String(q.id)] === opt}
                        onChange={() => updateAnswer(q.id, opt)}
                        className="w-5 h-5 text-blue-600 border-slate-300"
                      />
                      <span className="text-base text-slate-700">{opt}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between">
              <button
                onClick={() => setCurrent(p => Math.max(0, p - 1))}
                disabled={current === 0}
                className="px-5 py-2.5 text-sm border-2 border-slate-200 rounded-xl text-slate-600 hover:bg-slate-50 disabled:opacity-35 disabled:cursor-not-allowed transition-colors"
              >
                ← Өмнөх
              </button>
              <div className="text-sm text-slate-400">{current + 1} / {questions.length}</div>
              <button
                onClick={() => setCurrent(p => Math.min(questions.length - 1, p + 1))}
                disabled={current === questions.length - 1}
                className="px-5 py-2.5 text-sm bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-35 disabled:cursor-not-allowed transition-colors"
              >
                Дараах →
              </button>
            </div>
          </div>
        </div>

        <div className="flex flex-col w-64 gap-4 p-5 bg-white border-l border-slate-200">
          <div className="text-sm font-bold tracking-wider uppercase text-slate-400">Таны камер</div>
          <div className="relative overflow-hidden bg-black rounded-xl aspect-video">
            <video ref={videoRef} autoPlay muted playsInline className="object-cover w-full h-full" />
            {cameraOk && (
              <div className="absolute flex items-center gap-1 top-2 left-2">
                <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
                <span className="text-xs font-medium text-white">ХЯНАЛТ</span>
              </div>
            )}
          </div>

          <div className="p-4 bg-slate-50 rounded-xl">
            <p className="text-xs leading-relaxed text-slate-500">
              Камер, микрофоноор хянагдаж байна. Видео бичлэг хадгалагдахгүй — зөвхөн зөрчил илэрсэн
              мөчийн зураг багшид хадгалагдана.
            </p>
          </div>

          {flagCount > 0 && (
            <div className="p-4 border-2 border-red-200 bg-red-50 rounded-xl">
              <p className="text-sm font-bold text-red-600">{flagCount} анхааруулга бүртгэгдсэн</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
