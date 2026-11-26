'use client'

interface Event {
  timestamp: string
  severity: 'low' | 'medium' | 'high'
}

interface Props {
  events: Event[]
  windowMinutes?: number
  height?: number
}

export default function Sparkline({ events, windowMinutes = 30, height = 64 }: Props) {
  const buckets = 30
  const now = Date.now()
  const windowMs = windowMinutes * 60 * 1000
  const bucketMs = windowMs / buckets

  const data: { low: number; medium: number; high: number }[] = Array.from(
    { length: buckets },
    () => ({ low: 0, medium: 0, high: 0 })
  )

  for (const ev of events) {
    const t = new Date(ev.timestamp).getTime()
    const age = now - t
    if (age < 0 || age > windowMs) continue
    const idx = Math.min(buckets - 1, Math.floor((windowMs - age) / bucketMs))
    data[idx][ev.severity] = (data[idx][ev.severity] || 0) + 1
  }

  const maxCount = Math.max(1, ...data.map(d => d.low + d.medium + d.high))
  const barWidth = 100 / buckets
  const totalEvents = events.filter(e => now - new Date(e.timestamp).getTime() <= windowMs).length

  return (
    <div className="relative">
      <div className="flex items-center justify-between mb-2">
        <span className="ufe-caps text-[10px] text-slate-500 dark:text-slate-400">
          Сүүлийн {windowMinutes} мин
        </span>
        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
          {totalEvents} үйлдэл
        </span>
      </div>
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="w-full text-slate-200 dark:text-slate-700" style={{ height }}>
        <defs>
          <linearGradient id="grid-fade" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f1f5f9" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#f1f5f9" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((y, i) => (
          <line
            key={i}
            x1="0"
            y1={height * y}
            x2="100"
            y2={height * y}
            stroke="currentColor"
            strokeWidth="0.3"
            strokeDasharray="0.5 1"
          />
        ))}
        {data.map((bucket, i) => {
          const total = bucket.low + bucket.medium + bucket.high
          if (total === 0) return null
          const h = (total / maxCount) * (height - 8)
          const x = i * barWidth + barWidth * 0.15
          const w = barWidth * 0.7
          let yCursor = height - h
          return (
            <g key={i}>
              {bucket.high > 0 && (
                <rect
                  x={x} y={yCursor}
                  width={w}
                  height={(bucket.high / total) * h}
                  fill="#ef4444"
                  rx="0.4"
                />
              )}
              {bucket.medium > 0 && (
                <rect
                  x={x}
                  y={yCursor + (bucket.high / total) * h}
                  width={w}
                  height={(bucket.medium / total) * h}
                  fill="#f59e0b"
                  rx="0.4"
                />
              )}
              {bucket.low > 0 && (
                <rect
                  x={x}
                  y={yCursor + ((bucket.high + bucket.medium) / total) * h}
                  width={w}
                  height={(bucket.low / total) * h}
                  fill="#3b82f6"
                  rx="0.4"
                />
              )}
            </g>
          )
        })}
      </svg>
      <div className="flex gap-3 mt-2 text-[10px] text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-red-500" />Өндөр</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-amber-500" />Дунд</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-blue-500" />Бага</span>
      </div>
    </div>
  )
}
