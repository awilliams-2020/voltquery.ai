"use client"

import React from "react"
import { useState, useEffect, useCallback } from "react"
import { useUser } from "@clerk/nextjs"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { History, Calendar, MapPin } from "lucide-react"
import { format } from "date-fns"
import { parseMarkdown } from "@/lib/utils"

interface QueryHistoryItem {
  id: string
  question: string
  answer: string
  zip_code: string | null
  sources_count: number
  created_at: string
}

export default function HistoryPage() {
  const { user } = useUser()
  const [queries, setQueries] = useState<QueryHistoryItem[]>([])
  const [loading, setLoading] = useState(true)

  const fetchHistory = useCallback(async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
      const response = await fetch(`${apiUrl}/api/history/queries`, {
        headers: {
          "X-Clerk-User-Id": user?.id || "",
          "X-Clerk-Email": user?.primaryEmailAddress?.emailAddress || "",
        },
      })
      if (response.ok) {
        const data = await response.json()
        setQueries(data)
      }
    } catch (error) {
      console.error("Failed to fetch history:", error)
    } finally {
      setLoading(false)
    }
  }, [user?.id, user?.primaryEmailAddress?.emailAddress])

  useEffect(() => {
    if (user) {
      fetchHistory()
    }
  }, [user, fetchHistory])

  return (
    <div className="min-h-screen">
      <div className="container mx-auto px-4 py-8">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-center gap-3 mb-8">
            <History className="h-8 w-8 text-primary" />
            <h1 className="text-3xl font-bold">Query History</h1>
          </div>

          {loading ? (
            <div className="text-center py-12 text-muted-foreground">
              Loading history...
            </div>
          ) : queries.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <History className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
                <p className="text-muted-foreground">
                  No queries yet. Start asking questions to see your history here.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {queries.map((query) => (
                <Card key={query.id}>
                  <CardHeader>
                    <div className="flex items-start justify-between">
                      <CardTitle className="text-lg">{query.question}</CardTitle>
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Calendar className="h-4 w-4" />
                        {format(new Date(query.created_at), "MMM d, yyyy 'at' h:mm a")}
                      </div>
                    </div>
                    {query.zip_code && (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground mt-2">
                        <MapPin className="h-4 w-4" />
                        Zip: {query.zip_code}
                      </div>
                    )}
                  </CardHeader>
                  <CardContent>
                    <div className="prose prose-invert max-w-none">
                      <p className="text-sm text-muted-foreground mb-2">
                        Answer ({query.sources_count} sources):
                      </p>
                      <div className="space-y-2">
                        {parseMarkdown(query.answer).map((element, index) => (
                          <React.Fragment key={index}>{element}</React.Fragment>
                        ))}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

