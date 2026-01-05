import { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Query History',
  description: 'View your past queries about EV charging stations, electricity rates, solar energy, and energy optimization',
  robots: {
    index: false, // History pages shouldn't be indexed
    follow: false,
  },
}

export default function HistoryLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return children
}

