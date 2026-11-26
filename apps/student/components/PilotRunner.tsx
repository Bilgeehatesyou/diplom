'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '../lib/api'

export interface PilotStep {
  id: string
  text: string
  duration: number
  category: 'setup' | 'normal' | 'positive' | 'hard_negative'
  helper: boolean
}

export interface PilotProtocol {
  id: string
  steps: PilotStep[]
}

/**
 * Pilot үнэлгээний заавар (зөвхөн backend PILOT_MODE=1 үед гарна).
 * Алхам бүр эхлэхэд серверт тэмдэглэл илгээнэ → ground truth нь серверийн цагаар бүртгэгдэнэ.
 * Дохио: 1 өндөр = зөрчлийн үйлдлээ хий, 2 нам = хэвийн байдалд буц, 3 = дууслаа.
 */
export default function PilotRunner({ protocol, examId, ready }: {
  protocol: PilotProtocol
  examId: string
  ready: boolean
}) {
  const steps = protocol.steps
  const [index, setIndex] = useState(-1)          // -1 = эхлээгүй, steps.length = дууссан
  const [left, setLeft] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const endAtRef = useRef(0)
  const indexRef = useRef(-1)
  const audioRef = useRef<AudioContext | null>(null)

  const beep = (times: number, freq: number) => {
    const ctx = audioRef.current
    if (!ctx) return
    for (let i = 0; i < times; i++) {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.frequency.value = freq
      gain.gain.value = 0.15
      osc.connect(gain).connect(ctx.destination)
      const t = ctx.currentTime + i * 0.25
      osc.start(t)
      osc.stop(t + 0.15)
    }
  }

  const mark = useCallback((stepIndex: number, stepId: string, skipped = false) => {
    apiFetch('/api/pilot/mark', {
      method: 'POST',
      body: JSON.stringify({ exam_id: examId, step_index: stepIndex, step_id: stepId, skipped }),
    }).catch(e => setError(`Тэмдэглэл хадгалагдсангүй: ${e instanceof Error ? e.message : e}`))
  }, [examId])

  const startStep = useCallback((i: number) => {
    indexRef.current = i
    setIndex(i)
    if (i >= steps.length) {
      mark(steps.length, 'end')
      beep(3, 660)
      return
    }
    const s = steps[i]
    endAtRef.current = Date.now() + s.duration * 1000
    setLeft(s.duration)
    mark(i, s.id)
    if (s.category === 'positive' || s.category === 'hard_negative') beep(1, 880)
    else beep(2, 520)
  }, [steps, mark])

  useEffect(() => {
    const t = setInterval(() => {
      const i = indexRef.current
      if (i < 0 || i >= steps.length) return
      const l = Math.max(0, Math.ceil((endAtRef.current - Date.now()) / 1000))
      setLeft(l)
      if (l <= 0) startStep(i + 1)
    }, 250)
    return () => clearInterval(t)
  }, [steps.length, startStep])

  const handleStart = () => {
    try { audioRef.current = new AudioContext() } catch {}
    startStep(0)
  }

  const handleSkip = () => {
    const i = indexRef.current
    mark(i, steps[i].id, true)
    startStep(i + 1)
  }

  const totalMin = Math.round(steps.reduce((a, s) => a + s.duration, 0) / 60)
  const step = index >= 0 && index < steps.length ? steps[index] : null
  const tone = step?.category === 'positive' ? 'border-red-400 bg-red-50'
             : step?.category === 'hard_negative' ? 'border-amber-400 bg-amber-50'
             : 'border-blue-300 bg-white'

  return (
    <div className={`fixed bottom-4 left-1/2 -translate-x-1/2 z-[60] w-[min(720px,95vw)] rounded-xl border-2 shadow-2xl p-4 ${tone}`}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] font-bold tracking-wider uppercase text-slate-500">
          Pilot үнэлгээ · {protocol.id}{step ? ` · алхам ${index + 1}/${steps.length}` : ''}
        </span>
        {step && <span className="font-mono text-2xl font-bold tabular-nums text-slate-800">{left}с</span>}
      </div>

      {index < 0 && (
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm text-slate-700">
            {steps.length} алхамтай, ~{totalMin} минутын туршилт. Дэлгэцэн дээрх зааврыг дагана уу;
            дэлгэц рүү харахгүй үед дохиогоор чиглүүлнэ (1 өндөр дохио = үйлдлээ хий, 2 нам = хэвийн байдалд буц).
          </p>
          <button onClick={handleStart} disabled={!ready}
                  className="flex-shrink-0 px-4 py-2 text-sm font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {ready ? 'Туршилт эхлүүлэх' : 'Холбогдож байна…'}
          </button>
        </div>
      )}

      {step && (
        <>
          <p className="text-base font-semibold leading-snug text-slate-900">{step.text}</p>
          <div className="h-1.5 mt-3 overflow-hidden rounded-full bg-slate-200">
            <div className="h-full bg-blue-600 transition-all"
                 style={{ width: `${100 * (1 - left / step.duration)}%` }} />
          </div>
          {step.helper && (
            <button onClick={handleSkip} className="mt-2 text-xs text-slate-500 underline hover:text-slate-800">
              Туслах хүн байхгүй — алгасах
            </button>
          )}
        </>
      )}

      {index >= steps.length && (
        <p className="text-sm font-semibold text-emerald-700">Туршилт дууслаа. Баярлалаа! Одоо «Илгээх» товчийг дарна уу.</p>
      )}

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </div>
  )
}
