import type { Metadata } from "next"
import { Inter } from "next/font/google"
import { ClerkProviderWrapper } from "@/components/clerk-provider-wrapper"
import { AppHeader } from "@/components/app-header"
import "./globals.css"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: "Energy Audit AI - EV Infrastructure RAG SaaS",
  description: "AI-powered EV charging station finder with energy audits",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <ClerkProviderWrapper>
      <html lang="en" className="dark">
        <body className={inter.className}>
          <AppHeader />
          {children}
        </body>
      </html>
    </ClerkProviderWrapper>
  )
}
