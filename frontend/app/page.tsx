"use client"

import { useState, useEffect, useCallback } from "react"
import { useUser } from "@clerk/nextjs"
import { SignIn, SignUp } from "@clerk/nextjs"
import { QueryLimitBanner } from "@/components/query-limit-banner"
import { RAGQueryForm } from "@/components/rag-query-form"
import { RAGResponseCard } from "@/components/rag-response-card"
import { StructuredData } from "@/components/structured-data"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { CheckCircle2, XCircle, X } from "lucide-react"

interface QueryStats {
  queries_used: number
  queries_remaining: number
  query_limit: number
  plan: string
}

export default function Home() {
  const { isSignedIn, user } = useUser()
  const [stats, setStats] = useState<QueryStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [upgradeLoading, setUpgradeLoading] = useState(false)
  const [authMode, setAuthMode] = useState<"signin" | "signup">("signin")
  const [showSuccessMessage, setShowSuccessMessage] = useState(false)
  const [showCancelMessage, setShowCancelMessage] = useState(false)

  const fetchStats = useCallback(async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
      const response = await fetch(`${apiUrl}/api/history/stats`, {
        headers: {
          "X-Clerk-User-Id": user?.id || "",
          "X-Clerk-Email": user?.primaryEmailAddress?.emailAddress || "",
        },
      })
      if (response.ok) {
        const data = await response.json()
        setStats(data)
      }
    } catch (error) {
      console.error("Failed to fetch stats:", error)
    }
  }, [user?.id, user?.primaryEmailAddress?.emailAddress])

  useEffect(() => {
    if (isSignedIn) {
      fetchStats()
    }
    
    // Check for success/cancel parameters in URL
    const params = new URLSearchParams(window.location.search)
    if (params.get("success") === "true") {
      setShowSuccessMessage(true)
      // Refresh stats to show updated subscription
      if (isSignedIn) {
        setTimeout(() => fetchStats(), 1000)
      }
      // Clean up URL
      window.history.replaceState({}, "", window.location.pathname)
      // Hide message after 5 seconds
      setTimeout(() => setShowSuccessMessage(false), 5000)
    } else if (params.get("canceled") === "true") {
      setShowCancelMessage(true)
      // Clean up URL
      window.history.replaceState({}, "", window.location.pathname)
      // Hide message after 5 seconds
      setTimeout(() => setShowCancelMessage(false), 5000)
    }
  }, [isSignedIn, fetchStats])

  // Handle hash changes and link clicks for switching between sign-in/sign-up
  useEffect(() => {
    const handleHashChange = () => {
      if (window.location.hash === "#signup") {
        setAuthMode("signup")
      } else if (window.location.hash === "#signin") {
        setAuthMode("signin")
      }
    }

    // Intercept clicks on Clerk footer links
    const handleClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      const link = target.closest("a[href*='sign']")
      if (link) {
        const href = link.getAttribute("href")
        if (href?.includes("signup")) {
          e.preventDefault()
          setAuthMode("signup")
          window.history.replaceState(null, "", "#signup")
        } else if (href?.includes("signin")) {
          e.preventDefault()
          setAuthMode("signin")
          window.history.replaceState(null, "", "#signin")
        }
      }
    }

    handleHashChange()
    window.addEventListener("hashchange", handleHashChange)
    document.addEventListener("click", handleClick, true)
    
    return () => {
      window.removeEventListener("hashchange", handleHashChange)
      document.removeEventListener("click", handleClick, true)
    }
  }, [])

  const handleUpgrade = async () => {
    setUpgradeLoading(true)
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
      const response = await fetch(`${apiUrl}/api/stripe/create-checkout`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Clerk-User-Id": user?.id || "",
          "X-Clerk-Email": user?.primaryEmailAddress?.emailAddress || "",
        },
        body: JSON.stringify({
          success_url: `${window.location.origin}/?success=true`,
          cancel_url: `${window.location.origin}/?canceled=true`,
        }),
      })
      const data = await response.json()
      if (data.url) {
        window.location.href = data.url
      }
    } catch (error) {
      console.error("Failed to create checkout:", error)
      setUpgradeLoading(false)
    }
  }

  // Show loading state while checking auth
  if (isSignedIn === undefined) {
    return (
      <div className="min-h-screen">
        <div className="container mx-auto px-4 py-16">
          <div className="max-w-2xl mx-auto text-center">
            <p className="text-muted-foreground">Loading...</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <>
      <StructuredData />
      <div className="min-h-screen">
        {!isSignedIn ? (
        <div className="container mx-auto px-2 sm:px-4 py-8">
          <div className="max-w-md mx-auto w-full">
            <div className="text-center mb-8">
              <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold mb-4 leading-normal pb-1 bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
                Volt Query AI
              </h1>
              <p className="text-base sm:text-lg md:text-xl text-muted-foreground mb-6 px-2">
                AI-powered insights for EV charging, electricity rates, solar energy, and energy optimization
              </p>
            </div>

            {/* Auth Mode Toggle */}
            <div className="flex gap-2 mb-6 bg-card border border-border rounded-lg p-1">
              <Button
                variant={authMode === "signin" ? "default" : "ghost"}
                className="flex-1 min-w-0 text-sm sm:text-base"
                onClick={() => setAuthMode("signin")}
              >
                Sign In
              </Button>
              <Button
                variant={authMode === "signup" ? "default" : "ghost"}
                className="flex-1 min-w-0 text-sm sm:text-base"
                onClick={() => setAuthMode("signup")}
              >
                Sign Up
              </Button>
            </div>

            {/* Auth Forms */}
            <div className="bg-card border border-border rounded-lg shadow-lg p-3 sm:p-6 w-full">
              {authMode === "signin" ? (
                <SignIn
                  appearance={{
                    variables: {
                      colorPrimary: "hsl(217 91% 60%)",
                      colorBackground: "hsl(222 47% 8%)",
                      colorInputBackground: "hsl(217 32% 17%)",
                      colorInputText: "hsl(210 40% 98%)",
                      colorText: "hsl(210 40% 98%)",
                      colorTextSecondary: "hsl(215 20% 65%)",
                      colorTextOnPrimaryBackground: "hsl(222 47% 8%)",
                    },
                    elements: {
                      rootBox: "mx-auto",
                      card: "bg-transparent shadow-none border-0 p-0",
                      formButtonPrimary: "bg-primary hover:bg-primary/90 text-primary-foreground",
                      headerTitle: "text-foreground",
                      headerSubtitle: "text-muted-foreground",
                      formFieldInput: "bg-input border-input text-foreground",
                      formFieldLabel: "text-foreground",
                      formFieldSuccessText: "text-success",
                      formFieldErrorText: "text-destructive",
                      formFieldHintText: "text-muted-foreground",
                      footerActionLink: "text-primary cursor-pointer",
                      footerActionText: "text-muted-foreground",
                      identityPreviewText: "text-foreground",
                      identityPreviewEditButton: "text-primary",
                      otpCodeFieldInput: "bg-input border-input text-foreground",
                    },
                  }}
                  routing="hash"
                />
              ) : (
                <SignUp
                  appearance={{
                    variables: {
                      colorPrimary: "hsl(217 91% 60%)",
                      colorBackground: "hsl(222 47% 8%)",
                      colorInputBackground: "hsl(217 32% 17%)",
                      colorInputText: "hsl(210 40% 98%)",
                      colorText: "hsl(210 40% 98%)",
                      colorTextSecondary: "hsl(215 20% 65%)",
                      colorTextOnPrimaryBackground: "hsl(222 47% 8%)",
                    },
                    elements: {
                      rootBox: "mx-auto",
                      card: "bg-transparent shadow-none border-0 p-0",
                      formButtonPrimary: "bg-primary hover:bg-primary/90 text-primary-foreground",
                      headerTitle: "text-foreground",
                      headerSubtitle: "text-muted-foreground",
                      formFieldInput: "bg-input border-input text-foreground",
                      formFieldLabel: "text-foreground",
                      formFieldSuccessText: "text-success",
                      formFieldErrorText: "text-destructive",
                      formFieldHintText: "text-muted-foreground",
                      footerActionLink: "text-primary cursor-pointer",
                      footerActionText: "text-muted-foreground",
                      identityPreviewText: "text-foreground",
                      identityPreviewEditButton: "text-primary",
                      otpCodeFieldInput: "bg-input border-input text-foreground",
                    },
                  }}
                  routing="hash"
                />
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="container mx-auto px-4 py-8">
          <div className="max-w-4xl mx-auto">
            <div className="text-center mb-8">
              <h1 className="text-4xl font-bold mb-2 leading-normal pb-1 bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
                Volt Query AI
              </h1>
              <p className="text-muted-foreground">
                Ask questions about EV charging stations, electricity rates, solar energy, and energy optimization
              </p>
            </div>

            {showSuccessMessage && (
              <Card className="mb-6 border-green-500 bg-green-500/10">
                <CardContent className="pt-6">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <CheckCircle2 className="h-5 w-5 text-green-500" />
                      <div>
                        <p className="font-medium text-green-500">Upgrade Successful!</p>
                        <p className="text-sm text-muted-foreground">
                          Your Premium subscription is now active. Enjoy unlimited queries!
                        </p>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowSuccessMessage(false)}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            {showCancelMessage && (
              <Card className="mb-6 border-yellow-500 bg-yellow-500/10">
                <CardContent className="pt-6">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <XCircle className="h-5 w-5 text-yellow-500" />
                      <div>
                        <p className="font-medium text-yellow-500">Upgrade Canceled</p>
                        <p className="text-sm text-muted-foreground">
                          No charges were made. You can upgrade anytime from the banner above.
                        </p>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowCancelMessage(false)}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            {stats && (
              <QueryLimitBanner
                queriesUsed={stats.queries_used}
                queryLimit={stats.query_limit}
                plan={stats.plan}
                onUpgrade={handleUpgrade}
                upgradeLoading={upgradeLoading}
              />
            )}

            <RAGQueryForm onQueryComplete={fetchStats} />
          </div>
        </div>
      )}
      </div>
    </>
  )
}
