'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'

export default function HomePage() {
  const router  = useRouter()
  const [agreed, setAgreed] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleStart = async () => {
    if (!agreed) return
    setLoading(true)
    // Камер зөвшөөрөл
    try {
      await navigator.mediaDevices.getUserMedia({ video: true, audio: true })
      router.push('/exam')
    } catch {
      alert('Камер, микрофон зөвшөөрөл өгнө үү')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 w-full max-w-lg p-8">
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-blue-600 rounded-2xl flex items-center justify-center text-white text-2xl font-bold mx-auto mb-4">AI</div>
          <h1 className="text-xl font-bold text-gray-900">Мэдээллийн систем</h1>
          <p className="text-gray-500 text-sm mt-1">Улирлын шалгалт · СЭЗИС</p>
        </div>

        <div className="bg-gray-50 rounded-xl p-4 mb-6 text-sm text-gray-600 space-y-2">
          <p className="font-semibold text-gray-800">Шалгалтын дүрэм:</p>
          <p>• Шалгалтын турш камер заавал ажиллах ёстой</p>
          <p>• Бусад tab, програм нээхийг хориглоно</p>
          <p>• Гуравдагч этгээдийн оролцоог хориглоно</p>
          <p>• Гар утас болон тэмдэглэл хэрэглэхийг хориглоно</p>
          <p>• Бичлэг хийгдэж, шалгалтын дараа багш үзнэ</p>
        </div>

        <label className="flex items-start gap-3 mb-6 cursor-pointer">
          <input
            type="checkbox"
            checked={agreed}
            onChange={e => setAgreed(e.target.checked)}
            className="mt-0.5 w-4 h-4"
          />
          <span className="text-sm text-gray-700">
            Дээрх дүрэмтэй танилцаж, камер болон микрофоны бичлэгийг зөвшөөрч байна.
          </span>
        </label>

        <button
          onClick={handleStart}
          disabled={!agreed || loading}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white font-semibold py-3 rounded-xl transition-colors"
        >
          {loading ? 'Ачааллаж байна...' : 'Шалгалт эхлэх'}
        </button>
      </div>
    </div>
  )
}
