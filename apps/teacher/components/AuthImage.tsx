'use client'
import { useEffect, useState } from 'react'
import { apiBlob } from '../lib/api'

// Incident зураг нь нэвтрэлт шаарддаг тул <img src> шууд ажиллахгүй —
// Authorization header-тэй татаад object URL болгоно. Нэг зургийг дахин татахгүй.
const cache = new Map<string, Promise<string>>()

export function loadIncident(snapshot: string): Promise<string> {
  let p = cache.get(snapshot)
  if (!p) {
    p = apiBlob(`/api/incident/${snapshot}`).then(b => URL.createObjectURL(b))
    p.catch(() => cache.delete(snapshot))
    cache.set(snapshot, p)
  }
  return p
}

export default function AuthImage({ snapshot, className, alt = 'snapshot', onOpen }: {
  snapshot: string
  className?: string
  alt?: string
  onOpen?: (url: string) => void
}) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    loadIncident(snapshot).then(u => { if (alive) setUrl(u) }).catch(() => {})
    return () => { alive = false }
  }, [snapshot])

  if (!url) return <div className={`${className ?? ''} bg-slate-100 dark:bg-slate-800 animate-pulse`} />
  return <img src={url} alt={alt} className={className} onClick={() => onOpen?.(url)} />
}
