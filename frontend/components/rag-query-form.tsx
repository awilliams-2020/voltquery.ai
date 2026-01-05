"use client"

import { useState } from "react"
import { useUser } from "@clerk/nextjs"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Search, Zap } from "lucide-react"
import { RAGResponseCard } from "./rag-response-card"

interface RAGResponse {
  question: string
  answer: string
  sources: Array<{ text: string; metadata: any }>
  num_sources: number
}

interface RAGQueryFormProps {
  onQueryComplete?: () => void
}

export function RAGQueryForm({ onQueryComplete }: RAGQueryFormProps) {
  const { user } = useUser()
  const [question, setQuestion] = useState("")
  const [zipCode, setZipCode] = useState("")
  const [loading, setLoading] = useState(false)
  const [response, setResponse] = useState<RAGResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!question.trim()) return

    setLoading(true)
    setError(null)
    setResponse(null)

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
      const response = await fetch(`${apiUrl}/api/rag/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Clerk-User-Id": user?.id || "",
          "X-Clerk-Email": user?.primaryEmailAddress?.emailAddress || "",
        },
        body: JSON.stringify({
          question: question,
          zip_code: zipCode || undefined,
          top_k: 5,
        }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || "Failed to process query")
      }

      const data = await response.json()
      setResponse(data)
      if (onQueryComplete) {
        onQueryComplete()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-primary" />
            Ask a Question
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Input
                type="text"
                placeholder="e.g., Where can I charge my Tesla?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                disabled={loading}
                className="text-lg"
              />
            </div>
            <div className="flex gap-2">
              <Input
                type="text"
                placeholder="Zip code (optional)"
                value={zipCode}
                onChange={(e) => setZipCode(e.target.value)}
                disabled={loading}
                maxLength={5}
                pattern="[0-9]{5}"
                className="flex-1"
              />
              <Button type="submit" disabled={loading || !question.trim()}>
                {loading ? (
                  "Processing..."
                ) : (
                  <>
                    <Search className="h-4 w-4 mr-2" />
                    Ask
                  </>
                )}
              </Button>
            </div>
          </form>

          {error && (
            <div className="mt-4 p-4 bg-destructive/10 border border-destructive rounded-lg">
              <p className="text-destructive text-sm">{error}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {response && <RAGResponseCard response={response} />}
    </div>
  )
}

