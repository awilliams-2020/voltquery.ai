"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { MessageSquare } from "lucide-react"

export function RAGResponseSkeleton() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-primary" />
          Answer
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <Skeleton className="h-4 w-24 mb-2" />
          <Skeleton className="h-6 w-full" />
        </div>
        <div>
          <Skeleton className="h-4 w-20 mb-2" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        </div>
        <div>
          <Skeleton className="h-4 w-32 mb-2" />
          <div className="space-y-2">
            <Skeleton className="h-16 w-full rounded-lg" />
            <Skeleton className="h-16 w-full rounded-lg" />
            <Skeleton className="h-16 w-full rounded-lg" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

