'use client'

interface Props {
  score: number
  size?: number
  thickness?: number
}

export default function RiskGauge({ score, size = 140, thickness = 12 }: Props) {
  const clamped = Math.max(0, Math.min(100, score))
  const radius = (size - thickness) / 2
  const circumference = 2 * Math.PI * radius
  const dashOffset = circumference * (1 - clamped / 100)

  const level =
    clamped >= 60 ? { color: '#ef4444', glow: 'rgba(239,68,68,0.35)', label: 'Өндөр' } :
    clamped >= 30 ? { color: '#f59e0b', glow: 'rgba(245,158,11,0.30)', label: 'Дунд' } :
                    { color: '#10b981', glow: 'rgba(16,185,129,0.30)', label: 'Хэвийн' }

  return (
    <div className="relative inline-flex items-center justify-center text-slate-200 dark:text-slate-800" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="transform -rotate-90">
        <defs>
          <filter id={`glow-${level.color}`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={thickness}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={level.color}
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          style={{
            transition: 'stroke-dashoffset 700ms cubic-bezier(0.4, 0, 0.2, 1), stroke 300ms',
            filter: `drop-shadow(0 0 6px ${level.glow})`,
          }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold tabular-nums" style={{ color: level.color }}>
          {Math.round(clamped)}
        </span>
        <span className="mt-0.5 text-[10px] font-semibold tracking-wider uppercase text-slate-500 dark:text-slate-400">
          {level.label}
        </span>
      </div>
    </div>
  )
}
