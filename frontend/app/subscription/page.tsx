"use client"

import React from "react"
import { useState, useEffect, useCallback } from "react"
import { useUser } from "@clerk/nextjs"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { CreditCard, CheckCircle2, XCircle, Zap, Loader2 } from "lucide-react"
import { useRouter } from "next/navigation"

interface SubscriptionStats {
  queries_used: number
  queries_remaining: number
  query_limit: number
  plan: string
}

export default function SubscriptionPage() {
  const { user } = useUser()
  const router = useRouter()
  const [stats, setStats] = useState<SubscriptionStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [upgrading, setUpgrading] = useState(false)
  const [downgrading, setDowngrading] = useState(false)

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
    } finally {
      setLoading(false)
    }
  }, [user?.id, user?.primaryEmailAddress?.emailAddress])

  useEffect(() => {
    if (user) {
      fetchStats()
    }
    // Reset downgrading state when component mounts (e.g., returning from Stripe portal)
    setDowngrading(false)
  }, [user, fetchStats])

  // Reset downgrading state when page becomes visible (e.g., user clicks back button)
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        setDowngrading(false)
      }
    }

    const handleFocus = () => {
      setDowngrading(false)
    }

    document.addEventListener("visibilitychange", handleVisibilityChange)
    window.addEventListener("focus", handleFocus)

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange)
      window.removeEventListener("focus", handleFocus)
    }
  }, [])

  const handleUpgrade = async () => {
    setUpgrading(true)
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
          success_url: `${window.location.origin}/subscription?success=true`,
          cancel_url: `${window.location.origin}/subscription?canceled=true`,
        }),
      })
      const data = await response.json()
      if (data.url) {
        window.location.href = data.url
      }
    } catch (error) {
      console.error("Failed to create checkout:", error)
      setUpgrading(false)
    }
  }

  const handleOpenPortal = async () => {
    setDowngrading(true)
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
      const response = await fetch(`${apiUrl}/api/stripe/create-portal`, {
        method: "POST",
        headers: {
          "X-Clerk-User-Id": user?.id || "",
          "X-Clerk-Email": user?.primaryEmailAddress?.emailAddress || "",
        },
      })
      const data = await response.json()
      if (data.url) {
        window.location.href = data.url
      }
    } catch (error) {
      console.error("Failed to open portal:", error)
      setDowngrading(false)
    }
  }


  // Check for success/cancel parameters in URL and handle return from Stripe portal
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    
    // Reset downgrading state when component mounts or when returning from portal
    setDowngrading(false)
    
    if (params.get("success") === "true") {
      // Refresh stats to show updated subscription
      setTimeout(() => {
        fetchStats()
        router.replace("/subscription")
      }, 1000)
    } else if (params.get("canceled") === "true") {
      router.replace("/subscription")
    }
    // Note: We don't auto-refresh on normal return from portal to avoid unnecessary API calls
    // The user can manually refresh if needed, or we rely on webhooks to update the state
  }, [router, fetchStats])

  // Reset downgrading state on mount to handle back button navigation
  useEffect(() => {
    setDowngrading(false)
  }, [])

  if (loading) {
    return (
      <div className="min-h-screen">
        <div className="container mx-auto px-4 py-8">
          <div className="max-w-4xl mx-auto">
            <div className="text-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary mx-auto mb-4" />
              <p className="text-muted-foreground">Loading subscription details...</p>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const isPremium = stats?.plan === "premium"
  const usagePercentage = stats ? (stats.queries_used / stats.query_limit) * 100 : 0

  return (
    <div className="min-h-screen">
      <div className="container mx-auto px-4 py-8">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-center gap-3 mb-8">
            <CreditCard className="h-8 w-8 text-primary" />
            <h1 className="text-3xl font-bold">Subscription Management</h1>
          </div>

          {/* Current Plan Card */}
          <Card className="mb-6">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-2xl">Current Plan</CardTitle>
                  <CardDescription className="mt-1">
                    Manage your subscription and usage
                  </CardDescription>
                </div>
                {isPremium ? (
                  <div className="flex items-center gap-2 px-4 py-2 bg-green-500/10 border border-green-500/20 rounded-lg">
                    <CheckCircle2 className="h-5 w-5 text-green-500" />
                    <span className="font-semibold text-green-500">Premium</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 px-4 py-2 bg-muted border border-border rounded-lg">
                    <XCircle className="h-5 w-5 text-muted-foreground" />
                    <span className="font-semibold text-muted-foreground">Free</span>
                  </div>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Usage Stats */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium">Monthly Query Usage</span>
                  <span className="text-sm text-muted-foreground">
                    {stats?.queries_used || 0} / {stats?.query_limit || 0} queries
                  </span>
                </div>
                <div className="w-full bg-muted rounded-full h-2.5">
                  <div
                    className={`h-2.5 rounded-full transition-all ${
                      usagePercentage >= 90
                        ? "bg-red-500"
                        : usagePercentage >= 70
                        ? "bg-yellow-500"
                        : "bg-primary"
                    }`}
                    style={{ width: `${Math.min(usagePercentage, 100)}%` }}
                  />
                </div>
                {stats && stats.queries_remaining > 0 && (
                  <p className="text-sm text-muted-foreground mt-2">
                    {stats.queries_remaining} queries remaining this month
                  </p>
                )}
                {stats && stats.queries_remaining === 0 && !isPremium && (
                  <p className="text-sm text-yellow-500 mt-2">
                    You&apos;ve reached your monthly limit. Upgrade to continue or wait for next month&apos;s reset.
                  </p>
                )}
              </div>

              {/* Plan Details */}
              <div className="grid md:grid-cols-2 gap-4">
                <div className="p-4 border border-border rounded-lg">
                  <h3 className="font-semibold mb-2 flex items-center gap-2">
                    <Zap className="h-4 w-4 text-primary" />
                    Free Plan
                  </h3>
                  <ul className="space-y-1 text-sm text-muted-foreground">
                    <li>• {stats?.query_limit || 3} queries per month</li>
                    <li>• Basic features</li>
                    <li>• Community support</li>
                  </ul>
                </div>
                <div className="p-4 border border-primary rounded-lg bg-primary/5">
                  <h3 className="font-semibold mb-2 flex items-center gap-2">
                    <Zap className="h-4 w-4 text-primary" />
                    Premium Plan
                  </h3>
                  <ul className="space-y-1 text-sm text-muted-foreground">
                    <li>• Unlimited queries</li>
                    <li>• All premium features</li>
                    <li>• Priority support</li>
                  </ul>
                </div>
              </div>

              {/* Action Button */}
              {!isPremium && (
                <Button
                  onClick={handleUpgrade}
                  disabled={upgrading}
                  className="w-full"
                  size="lg"
                >
                  {upgrading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Processing...
                    </>
                  ) : (
                    <>
                      <CreditCard className="mr-2 h-4 w-4" />
                      Upgrade to Premium
                    </>
                  )}
                </Button>
              )}

              {isPremium && (
                <div className="space-y-4">
                  <div className="p-4 bg-green-500/10 border border-green-500/20 rounded-lg">
                    <p className="text-sm text-green-500 font-medium">
                      <CheckCircle2 className="h-4 w-4 inline mr-2" />
                      Your premium subscription is active. Enjoy unlimited queries!
                    </p>
                  </div>
                  
                  <Button
                    onClick={handleOpenPortal}
                    disabled={downgrading}
                    variant="outline"
                    className="w-full"
                    size="lg"
                  >
                    {downgrading ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Loading...
                      </>
                    ) : (
                      <>
                        <CreditCard className="mr-2 h-4 w-4" />
                        Manage Billing
                      </>
                    )}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Account Info */}
          <Card>
            <CardHeader>
              <CardTitle>Account Information</CardTitle>
              <CardDescription>
                Your account details and billing information
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-sm text-muted-foreground">Email</span>
                  <span className="text-sm font-medium">{user?.primaryEmailAddress?.emailAddress}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-muted-foreground">User ID</span>
                  <span className="text-sm font-mono text-muted-foreground">{user?.id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-muted-foreground">Plan Status</span>
                  <span className="text-sm font-medium capitalize">{stats?.plan || "Unknown"}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

