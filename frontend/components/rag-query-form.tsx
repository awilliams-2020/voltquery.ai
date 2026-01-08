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
  detected_location?: {
    type?: string
    zip_code?: string
    city?: string
    state?: string
  }
  reranked?: boolean
  utility_rates?: any
}

interface RAGQueryFormProps {
  onQueryComplete?: () => void
}

type LoadingStage = 
  | "analyzing" 
  | "searching" 
  | "retrieving" 
  | "preparing"
  | "generating"
  | "processing"
  | "finalizing"
  | null

const LOADING_STAGES: Array<{ stage: LoadingStage; message: string; delay: number }> = [
  { stage: "analyzing", message: "Analyzing your question...", delay: 500 },
  { stage: "searching", message: "Searching for relevant information...", delay: 1500 },
  { stage: "retrieving", message: "Retrieving data from knowledge base...", delay: 2500 },
  { stage: "preparing", message: "Preparing query for AI...", delay: 3500 },
  { stage: "generating", message: "Generating response...", delay: 4000 },
  { stage: "processing", message: "Processing answer...", delay: 4500 },
  { stage: "finalizing", message: "Finalizing response...", delay: 5000 },
]

const STORAGE_KEY_RESPONSE = "rag-last-response"

export function RAGQueryForm({ onQueryComplete }: RAGQueryFormProps) {
  const { user } = useUser()
  const [question, setQuestion] = useState("")
  const [zipCode, setZipCode] = useState("")
  const [loading, setLoading] = useState(false)
  const [loadingStage, setLoadingStage] = useState<LoadingStage>(null)
  const [loadingMessage, setLoadingMessage] = useState<string>("Processing your question...")
  const [response, setResponse] = useState<RAGResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const stageTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Restore response from sessionStorage on mount (only restore results, not input)
  useEffect(() => {
    if (typeof window !== "undefined") {
      try {
        const savedResponse = sessionStorage.getItem(STORAGE_KEY_RESPONSE)
        
        if (savedResponse) {
          const parsedResponse = JSON.parse(savedResponse)
          setResponse(parsedResponse)
        }
      } catch (err) {
        console.error("Failed to restore response from sessionStorage:", err)
      }
    }
  }, [])

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (stageTimeoutRef.current) {
        clearTimeout(stageTimeoutRef.current)
      }
    }
  }, [])


  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!question.trim()) return

    setLoading(true)
    setError(null)
    setResponse(null)
    setLoadingStage("analyzing")
    setLoadingMessage("Analyzing your question...")
    
    // Clear inputs after submission
    const submittedQuestion = question
    const submittedZipCode = zipCode
    setQuestion("")
    setZipCode("")
    
    // Clear sessionStorage for new query (only store response, not input)
    if (typeof window !== "undefined") {
      sessionStorage.removeItem(STORAGE_KEY_RESPONSE)
    }
    
    // Clear any existing timeout
    if (stageTimeoutRef.current) {
      clearTimeout(stageTimeoutRef.current)
    }

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
      const response = await fetch(`${apiUrl}/api/rag/query-stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Clerk-User-Id": user?.id || "",
          "X-Clerk-Email": user?.primaryEmailAddress?.emailAddress || "",
        },
        body: JSON.stringify({
          question: submittedQuestion,
          zip_code: submittedZipCode || undefined,
          top_k: 5,
        }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: "Failed to process query" }))
        throw new Error(errorData.detail || "Failed to process query")
      }

      // Handle SSE stream
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      let currentResponse: Partial<RAGResponse> = {
        question: submittedQuestion,
        answer: "",
        sources: [],
        num_sources: 0,
      }

      if (!reader) {
        throw new Error("Failed to get response stream")
      }

      let eventCount = 0

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          break
        }

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n\n")
        buffer = lines.pop() || "" // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.trim() === "") continue

          eventCount++

          // Handle multi-line SSE format
          const parts = line.split("\n")
          let eventLine = ""
          let dataLine = ""
          
          for (const part of parts) {
            if (part.startsWith("event:")) {
              eventLine = part
            } else if (part.startsWith("data:")) {
              dataLine = part
            }
          }

          if (!eventLine || !dataLine) {
            console.warn(`[RAG Query] [Event #${eventCount}] Invalid SSE format - missing event or data line:`, { 
              eventLine, 
              dataLine, 
              allParts: parts,
              rawLine: line 
            })
            continue
          }

          const eventMatch = eventLine.match(/^event:\s*(.+)$/)
          const dataMatch = dataLine.match(/^data:\s*(.+)$/)

          if (!eventMatch || !dataMatch) {
            console.warn(`[RAG Query] [Event #${eventCount}] Failed to parse SSE event:`, { 
              eventLine, 
              dataLine, 
              eventMatch, 
              dataMatch,
              rawLine: line 
            })
            continue
          }

          const eventType = eventMatch[1].trim()
          let data
          try {
            data = JSON.parse(dataMatch[1].trim())
          } catch (e) {
            console.error(`[RAG Query] Failed to parse JSON data:`, dataMatch[1], e)
            continue
          }

          // Handle different event types
          if (eventType === "status") {
            const stage = data.stage
            const message = data.message || "Processing your question..."
            
            // Map backend stage to frontend stage
            let newStage: LoadingStage = null
            if (stage === "analyzing") {
              newStage = "analyzing"
            } else if (stage === "searching") {
              newStage = "searching"
            } else if (stage === "retrieving") {
              newStage = "retrieving"
            } else if (stage === "preparing") {
              newStage = "preparing"
            } else if (stage === "generating") {
              newStage = "generating"
            } else if (stage === "processing") {
              newStage = "processing"
            } else if (stage === "finalizing") {
              newStage = "finalizing"
            } else if (stage === "synthesizing") {
              // Legacy stage name - map to generating for backwards compatibility
              newStage = "generating"
            } else {
              console.warn(`[RAG Query] Unknown stage: ${stage}`)
            }
            
            // Update React state
            setLoadingMessage(message)
            setLoadingStage(newStage)
          } else if (eventType === "tool") {
            // Tool call notification
          } else if (eventType === "chunk") {
            // Stream answer chunks (if supported)
            currentResponse.answer = (currentResponse.answer || "") + data.text
            const chunkResponse: RAGResponse = {
              question: currentResponse.question || submittedQuestion,
              answer: currentResponse.answer || "",
              sources: currentResponse.sources || [],
              num_sources: currentResponse.num_sources || 0,
              detected_location: currentResponse.detected_location,
              reranked: currentResponse.reranked,
              utility_rates: currentResponse.utility_rates,
            }
            setResponse(chunkResponse)
          } else if (eventType === "done") {
            // Final response
            const finalResponse: RAGResponse = {
              question: data.question || submittedQuestion,
              answer: data.answer || "",
              sources: data.sources || [],
              num_sources: data.num_sources || 0,
              detected_location: data.detected_location,
              reranked: data.reranked,
              utility_rates: data.utility_rates,
            }
            setResponse(finalResponse)
            
            // Save response to sessionStorage
            if (typeof window !== "undefined") {
              try {
                sessionStorage.setItem(STORAGE_KEY_RESPONSE, JSON.stringify(finalResponse))
              } catch (err) {
                console.error("Failed to save response to sessionStorage:", err)
              }
            }
            
            if (onQueryComplete) {
              onQueryComplete()
            }
          } else if (eventType === "error") {
            throw new Error(data.message || "An error occurred")
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred")
    } finally {
      setLoading(false)
      setLoadingStage(null)
      setLoadingMessage("Processing your question...")
      if (stageTimeoutRef.current) {
        clearTimeout(stageTimeoutRef.current)
        stageTimeoutRef.current = null
      }
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
                placeholder="e.g., Where can I charge my Tesla? What's the electricity rate in Denver? How much solar can I generate?"
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
            <>
              <div className="mt-4 p-4 bg-primary/5 border border-primary/20 rounded-lg">
                <div className="flex items-center gap-3">
                  <Spinner size="sm" />
                  <p className="text-sm text-muted-foreground animate-pulse">
                    {loadingMessage}
                  </p>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {loading && <RAGResponseSkeleton />}
      {response && <RAGResponseCard response={response} />}
    </div>
  )
}

