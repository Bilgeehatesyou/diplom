import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'AI Proctor — Шалгалт',
  description: 'Онлайн шалгалтын систем',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="mn">
      <body>{children}</body>
    </html>
  )
}
