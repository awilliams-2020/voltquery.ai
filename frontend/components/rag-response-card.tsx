"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { MessageSquare, MapPin } from "lucide-react"

interface RAGResponse {
  question: string
  answer: string
  sources: Array<{ text: string; metadata: any }>
  num_sources: number
}

interface RAGResponseCardProps {
  response: RAGResponse
}

export function RAGResponseCard({ response }: RAGResponseCardProps) {
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
          <p className="text-sm text-muted-foreground mb-2">Question:</p>
          <p className="font-medium">{response.question}</p>
        </div>
        <div>
          <p className="text-sm text-muted-foreground mb-2">Answer:</p>
          <div className="prose prose-invert max-w-none">
            <p className="whitespace-pre-wrap">{response.answer}</p>
          </div>
        </div>
        {response.sources && response.sources.length > 0 && (
          <div>
            <p className="text-sm text-muted-foreground mb-2 flex items-center gap-2">
              <MapPin className="h-4 w-4" />
              Sources ({response.num_sources}):
            </p>
            <div className="space-y-2">
              {response.sources.slice(0, 3).map((source, index) => (
                <div
                  key={index}
                  className="p-3 bg-secondary/50 rounded-lg text-sm"
                >
                  <p className="text-muted-foreground line-clamp-2">
                    {source.text}
                  </p>
                  {source.metadata?.station_name && (
                    <p className="text-xs text-primary mt-1">
                      {source.metadata.station_name}
                      {source.metadata.city && `, ${source.metadata.city}`}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

