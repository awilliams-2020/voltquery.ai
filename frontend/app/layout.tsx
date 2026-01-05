import type { Metadata } from "next"
import { Inter } from "next/font/google"
import { ClerkProviderWrapper } from "@/components/clerk-provider-wrapper"
import { AppHeader } from "@/components/app-header"
import "./globals.css"

const inter = Inter({ subsets: ["latin"] })

const baseUrl = process.env.NEXT_PUBLIC_BASE_URL || 'https://voltquery.ai'

export const metadata: Metadata = {
  metadataBase: new URL(baseUrl),
  title: {
    default: "Volt Query AI | Energy Insights",
    template: "%s | Energy Insights",
  },
  description: "AI-powered insights for EV charging stations, electricity rates, solar energy production, and energy system optimization. Get instant answers about EV infrastructure, utility costs, and renewable energy.",
  keywords: [
    "EV charging stations",
    "electric vehicle infrastructure",
    "electricity rates",
    "utility costs",
    "solar energy",
    "energy optimization",
    "RAG AI",
    "EV charging finder",
    "renewable energy",
    "energy audit",
    "NREL API",
    "electric vehicle",
    "charging station locator",
    "solar production",
    "energy system optimization",
  ],
  authors: [{ name: "Energy Insights" }],
  creator: "Energy Insights",
  publisher: "Energy Insights",
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: baseUrl,
    siteName: "Energy Insights",
    title: "Energy Insights",
    description: "AI-powered insights for EV charging stations, electricity rates, solar energy production, and energy system optimization",
    images: [
      {
        url: `${baseUrl}/opengraph-image`,
        width: 1200,
        height: 630,
        alt: "Energy Insights",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Energy Insights",
    description: "AI-powered insights for EV charging stations, electricity rates, solar energy production, and energy system optimization",
    images: [`${baseUrl}/opengraph-image`],
    creator: "@voltqueryai",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  icons: {
    icon: [
      { url: "/favicon.svg", type: "image/svg+xml" },
    ],
    apple: [
      { url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
  },
  manifest: "/site.webmanifest",
  alternates: {
    canonical: baseUrl,
  },
  category: "technology",
  other: {
    "ai-agent": "Energy Insights RAG System",
    "ai-capabilities": "EV charging stations, electricity rates, solar energy, energy optimization",
    "ai-version": "1.0.0",
    "ai-type": "RAG (Retrieval-Augmented Generation)",
    "ai-domain": "EV Infrastructure, Energy Analytics, Renewable Energy",
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <ClerkProviderWrapper>
      <html lang="en" className="dark">
        <head>
          <meta name="ai-agent" content="Energy Insights RAG System" />
          <meta name="ai-capabilities" content="EV charging stations, electricity rates, solar energy, energy optimization" />
          <meta name="ai-version" content="1.0.0" />
          <meta name="ai-type" content="RAG (Retrieval-Augmented Generation)" />
        </head>
        <body className={inter.className}>
          <AppHeader />
          {children}
        </body>
      </html>
    </ClerkProviderWrapper>
  )
}
