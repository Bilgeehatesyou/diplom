export default function DonePage() {
  return (
    <div className="min-h-screen bg-slate-100 flex items-center justify-center p-6">
      <div className="bg-white rounded-lg border border-slate-200 p-10 text-center max-w-sm shadow-sm">
        <div className="w-12 h-12 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
          <svg className="w-6 h-6 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-base font-semibold text-slate-800 mb-2">Шалгалт амжилттай илгээгдлээ</h1>
        <p className="text-sm text-slate-500 leading-relaxed">
          Таны хариултууд хүлээн авч, хадгалагдлаа. Үр дүнг багшаас мэдэгдэнэ.
        </p>
        <div className="mt-6 pt-5 border-t border-slate-100">
          <p className="text-xs text-slate-400">СЭЗИС · Мэдээллийн систем · 2026</p>
        </div>
      </div>
    </div>
  )
}