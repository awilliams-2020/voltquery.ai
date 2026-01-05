"use client"

import { AlertCircle, Zap, Loader2 } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

interface QueryLimitBannerProps {
  queriesUsed: number
  queryLimit: number
  plan: string
  onUpgrade?: () => void
  upgradeLoading?: boolean
}

export function QueryLimitBanner({
  queriesUsed,
  queryLimit,
  plan,
  onUpgrade,
  upgradeLoading = false,
}: QueryLimitBannerProps) {
  const isPremium = plan === "premium"
  
  // Don't show banner for premium users
  if (isPremium) {
    return null
  }

  const remaining = queryLimit - queriesUsed
  const percentage = (queriesUsed / queryLimit) * 100
  const isNearLimit = percentage >= 80
  const isAtLimit = remaining === 0

  return (
    <Card className={`mb-6 ${isAtLimit ? "border-destructive" : isNearLimit ? "border-yellow-500" : ""}`}>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {isAtLimit ? (
              <AlertCircle className="h-5 w-5 text-destructive" />
            ) : (
              <Zap className="h-5 w-5 text-primary" />
            )}
            <div>
              <p className="font-medium">
                {isAtLimit
                  ? "Query limit reached"
                  : `${remaining} query${remaining !== 1 ? "s" : ""} remaining`}
              </p>
              <p className="text-sm text-muted-foreground">
                {queriesUsed} of {queryLimit} queries used this month
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="w-32 h-2 bg-secondary rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${
                  isAtLimit
                    ? "bg-destructive"
                    : isNearLimit
                    ? "bg-yellow-500"
                    : "bg-primary"
                }`}
                style={{ width: `${Math.min(percentage, 100)}%` }}
              />
            </div>
            {onUpgrade && (
              <Button onClick={onUpgrade} size="sm" disabled={upgradeLoading}>
                {upgradeLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Loading...
                  </>
                ) : (
                  "Upgrade"
                )}
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

