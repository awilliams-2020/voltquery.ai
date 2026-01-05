import { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Subscription Management',
  description: 'Manage your subscription, view usage, and upgrade your plan',
  robots: {
    index: false, // Subscription pages shouldn't be indexed
    follow: false,
  },
}

export default function SubscriptionLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return children
}

