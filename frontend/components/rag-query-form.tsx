"use client"

import { useState, useEffect, useRef } from "react"
import { useUser } from "@clerk/nextjs"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Search, Zap } from "lucide-react"
import { RAGResponseCard } from "./rag-response-card"
import { RAGResponseSkeleton } from "./rag-response-skeleton"
import { Spinner } from "@/components/ui/spinner"

interface RAGResponse {
  question: string
  answer: string
  sources: Array<{ text: string; metadata: any }>
  num_sources: number
}

interface RAGQueryFormProps {
  onQueryComplete?: () => void
}

type LoadingStage = 
  | "analyzing" 
  | "searching" 
  | "retrieving" 
  | "generating" 
  | null

const LOADING_STAGES: Array<{ stage: LoadingStage; message: string; delay: number }> = [
  { stage: "analyzing", message: "Analyzing your question...", delay: 500 },
  { stage: "searching", message: "Searching for relevant information...", delay: 1500 },
  { stage: "retrieving", message: "Retrieving data from knowledge base...", delay: 2500 },
  { stage: "generating", message: "Generating response...", delay: 3500 },
]

export function RAGQueryForm({ onQueryComplete }: RAGQueryFormProps) {
  const { user } = useUser()
  const [question, setQuestion] = useState("")
  const [zipCode, setZipCode] = useState("")
  const [loading, setLoading] = useState(false)
  const [loadingStage, setLoadingStage] = useState<LoadingStage>(null)
  const [response, setResponse] = useState<RAGResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const stageTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (stageTimeoutRef.current) {
        clearTimeout(stageTimeoutRef.current)
      }
    }
  }, [])

  const startProgressiveLoading = () => {
    let currentIndex = 0
    
    const advanceStage = () => {
      if (currentIndex < LOADING_STAGES.length) {
        const currentStage = LOADING_STAGES[currentIndex]
        setLoadingStage(currentStage.stage)
        
        if (currentIndex < LOADING_STAGES.length - 1) {
          const nextStage = LOADING_STAGES[currentIndex + 1]
          const delay = nextStage.delay - currentStage.delay
          stageTimeoutRef.current = setTimeout(() => {
            currentIndex++
            advanceStage()
          }, delay)
        }
        // If we're at the last stage, stay there until response arrives
      }
    }
    
    advanceStage()
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!question.trim()) return

    setLoading(true)
    setError(null)
    setResponse(null)
    setLoadingStage("analyzing")
    
    // Clear any existing timeout
    if (stageTimeoutRef.current) {
      clearTimeout(stageTimeoutRef.current)
    }
    
    // Start progressive loading stages
    startProgressiveLoading()

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
      setLoadingStage(null)
      if (stageTimeoutRef.current) {
        clearTimeout(stageTimeoutRef.current)
        stageTimeoutRef.current = null
      }
    }
  }
  
  const getLoadingMessage = () => {
    const stage = LOADING_STAGES.find(s => s.stage === loadingStage)
    return stage?.message || "Processing your question..."
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
                  <span className="flex items-center gap-2">
                    <Spinner size="sm" />
                    Processing...
                  </span>
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

          {loading && (
            <div className="mt-4 p-4 bg-primary/5 border border-primary/20 rounded-lg">
              <div className="flex items-center gap-3">
                <Spinner size="sm" />
                <p className="text-sm text-muted-foreground animate-pulse">
                  {getLoadingMessage()}
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {loading && <RAGResponseSkeleton />}
      {response && <RAGResponseCard response={response} />}
    </div>
  )
}

