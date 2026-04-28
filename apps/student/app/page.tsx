'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'

export default function HomePage() {
  const router = useRouter()
  const [agreed, setAgreed] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleStart = async () => {
    if (!agreed) return
    setLoading(true)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      })
      stream.getTracks().forEach(t => t.stop())
      router.push('/exam')
    } catch {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-100 flex items-center justify-center p-6">
      <div className="w-full max-w-md">

        {/* Branding */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-12 h-12 bg-blue-600 rounded-lg mb-4">
            <span className="text-white text-lg font-bold tracking-tight">AP</span>
          </div>
          <h1 className="text-lg font-semibold text-slate-800">AI Proctor</h1>
          <p className="text-sm text-slate-500 mt-1">Онлайн шалгалтын хяналтын систем</p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm">
          <div className="px-6 pt-6 pb-4">
            <h2 className="text-base font-semibold text-slate-800 mb-1">Шалгалт эхлэх</h2>
            <p className="text-xs text-slate-500">Улирлын шалгалт · СЭЗИС МСМ</p>
          </div>

          <div className="px-6 pb-4">
            <div className="bg-slate-50 rounded-lg p-4 mb-5">
              <p className="text-xs font-semibold text-slate-600 mb-3 uppercase tracking-wide">Шалгалтын нөхцөл</p>
              <ul className="space-y-2">
                {[
                  'Камер болон микрофон ажиллах ёстой',
                  'Шалгалтын явцад өөр tab нээхгүй байх',
                  'Гар утас, гадаад төхөөрөмж хориглоно',
                  'Бүх үйлдэл хянагдан бичлэглэгдэнэ',
                ].map((rule, i) => (
                  <li key={i} className="flex items-start gap-2.5 text-xs text-slate-600">
                    <span className="flex-shrink-0 w-4 h-4 bg-slate-200 rounded-full flex items-center justify-center text-slate-500 mt-0.5">
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
                  className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
              </div>
              <span className="text-xs text-slate-600 leading-relaxed">
                Дээрх нөхцөлтэй танилцаж, хяналтын системийг зөвшөөрч байна.
              </span>
            </label>

            <button
              onClick={handleStart}
              disabled={!agreed || loading}
              className="w-full py-2.5 text-sm font-semibold rounded-lg transition-colors text-white bg-blue-600 hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400 cursor-pointer"
            >
              {loading ? 'Бэлдэж байна...' : 'Шалгалт эхлэх'}
            </button>
          </div>

          <div className="px-6 pb-5 text-center">
            <p className="text-xs text-slate-400">
              Асуудал гарвал багштай холбогдоно уу
            </p>
          </div>
        </div>

        <p className="text-center text-xs text-slate-400 mt-6">
          СЭЗИС · Мэдээллийн систем · 2026
        </p>
      </div>
    </div>
  )
}