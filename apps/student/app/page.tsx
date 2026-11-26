'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import ThemeToggle from '../components/ThemeToggle'
import { getStudent, clearStudent, StudentAuth } from '../lib/api'

export default function HomePage() {
  const router = useRouter()
  const [student, setStudent] = useState<StudentAuth | null>(null)
  const [agreed, setAgreed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const s = getStudent()
    if (!s) {
      router.push('/login')
      return
    }
    setStudent(s)
  }, [router])

  const handleStart = async () => {
    if (!agreed) return
    setLoading(true)
    setError(null)
    // Fullscreen-ийг хэрэглэгчийн click дотор (await-ээс өмнө) хүсэх ёстой
    document.documentElement.requestFullscreen?.().catch(() => {})
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('Энэ browser нь камер ашиглах боломжгүй. Chrome эсвэл Edge ашиглана уу.')
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: true,
      })
      stream.getTracks().forEach(t => t.stop())
      router.push('/exam')
    } catch (err: any) {
      console.error('[handleStart] error:', err)
      let msg = 'Камер/микрофон ашиглах боломжгүй байна.'
      if (err?.name === 'NotAllowedError' || err?.name === 'PermissionDeniedError') {
        msg = 'Камер/микрофон зөвшөөрөл татгалзагдсан. Browser-н тохиргооноос зөвшөөрөл өгнө үү.'
      } else if (err?.name === 'NotFoundError' || err?.name === 'DevicesNotFoundError') {
        msg = 'Камер/микрофон олдсонгүй. Холбогдсон эсэхээ шалгана уу.'
      } else if (err?.name === 'NotReadableError') {
        msg = 'Камер/микрофон өөр программ ашиглаж байна. Тэрийг хааж дахин оролдоно уу.'
      } else if (err?.message) {
        msg = err.message
      }
      setError(msg)
      setLoading(false)
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
    }
  }

  const handleLogout = () => {
    clearStudent()
    router.push('/login')
  }

  if (!student) return null

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center p-6">
      <div className="absolute top-6 right-6">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 bg-gradient-to-br from-ufe-600 to-ufe-700 rounded-lg mb-4 shadow-md shadow-ufe-500/30">
            <span className="text-white text-lg font-bold tracking-tight">AP</span>
          </div>
          <h1 className="ufe-caps text-base text-slate-900 dark:text-slate-100">AI Proctor</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">Онлайн шалгалтын хяналтын систем</p>
        </div>

        <div className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="px-6 pt-6 pb-4 flex items-start justify-between">
            <div>
              <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100 mb-1">Шалгалт эхлэх</h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">{student.name} · {student.student_id}</p>
              <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">{student.department}</p>
            </div>
            <button
              onClick={handleLogout}
              className="ufe-caps text-[10px] text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
            >
              Гарах
            </button>
          </div>

          <div className="px-6 pb-4">
            <div className="bg-slate-50 dark:bg-slate-950 rounded-lg p-4 mb-5">
              <p className="ufe-caps text-[10px] text-slate-600 dark:text-slate-300 mb-3">Шалгалтын нөхцөл</p>
              <ul className="space-y-2">
                {[
                  'Камер болон микрофон ажиллах ёстой; шалгалт бүтэн дэлгэцээр явагдана',
                  'Шалгалтын явцад өөр tab, цонх нээхгүй байх',
                  'Гар утас, ном, гадаад төхөөрөмж хориглоно',
                  'Камер/микрофоны урсгалыг AI шинжилнэ. Видео бичлэг хадгалагдахгүй; зөвхөн зөрчил илэрсэн мөчийн зураг, үйлдлийн бүртгэл багшид хадгалагдана',
                  'Систем шийдвэр гаргахгүй — эцсийн шийдвэрийг багш зураг, бүртгэлийг хянаж гаргана',
                ].map((rule, i) => (
                  <li key={i} className="flex items-start gap-2.5 text-xs text-slate-600 dark:text-slate-300">
                    <span className="flex-shrink-0 w-4 h-4 bg-slate-200 dark:bg-slate-800 rounded-full flex items-center justify-center text-slate-500 dark:text-slate-400 mt-0.5 text-[10px] font-semibold tabular-nums">
                      {i + 1}
                    </span>
                    {rule}
                  </li>
                ))}
              </ul>
            </div>

            <label className="flex items-start gap-3 cursor-pointer mb-5">
              <div className="mt-0.5">
                <input
                  type="checkbox"
                  checked={agreed}
                  onChange={e => setAgreed(e.target.checked)}
                  className="w-4 h-4 rounded border-slate-300 dark:border-slate-600 text-ufe-600 focus:ring-ufe-500"
                />
              </div>
              <span className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
                Дээрх нөхцөлтэй танилцаж, хяналтын системийг зөвшөөрч байна.
              </span>
            </label>

            {error && (
              <div className="mb-4 text-xs text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/50 rounded-md px-3 py-2">
                {error}
              </div>
            )}

            <button
              onClick={handleStart}
              disabled={!agreed || loading}
              className="ufe-caps w-full py-2.5 text-sm rounded-lg transition-colors text-white bg-ufe-600 hover:bg-ufe-700 disabled:bg-slate-200 dark:disabled:bg-slate-800 disabled:text-slate-400 dark:disabled:text-slate-500 cursor-pointer"
            >
              {loading ? 'Бэлдэж байна...' : 'Шалгалт эхлэх'}
            </button>
          </div>

          <div className="px-6 pb-5 text-center">
            <p className="text-xs text-slate-400 dark:text-slate-500">Асуудал гарвал багштай холбогдоно уу</p>
          </div>
        </div>

        <p className="ufe-caps text-center text-[10px] text-slate-400 dark:text-slate-500 mt-6">СЭЗИС · Мэдээллийн систем · 2026</p>
      </div>
    </div>
  )
}
