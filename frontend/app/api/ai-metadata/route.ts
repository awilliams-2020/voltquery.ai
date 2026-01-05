import { NextResponse } from 'next/server'

export async function GET() {
  const baseUrl = process.env.NEXT_PUBLIC_BASE_URL || 'https://voltquery.ai'
  
  const aiMetadata = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "name": "Volt Query AI",
    "version": "1.0.0",
    "applicationCategory": "UtilityApplication",
    "operatingSystem": "Web",
    "description": "AI-powered RAG (Retrieval-Augmented Generation) SaaS application providing intelligent insights about EV charging stations, electricity rates, solar energy production, and energy system optimization",
    "url": baseUrl,
    "author": {
      "@type": "Organization",
      "name": "Volt Query AI"
    },
    "offers": {
      "@type": "Offer",
      "price": "0",
      "priceCurrency": "USD"
    },
    "featureList": [
      "Natural language query processing",
      "EV charging station location queries",
      "Electricity rate and utility cost queries",
      "Solar energy production estimates",
      "Energy system optimization analysis",
      "Location-based data retrieval",
      "RAG-based information retrieval"
    ],
    "knowsAbout": [
      "EV charging infrastructure",
      "Electricity rates",
      "Utility costs",
      "Solar energy",
      "Energy optimization",
      "Renewable energy",
      "Electric vehicles"
    ],
    "audience": {
      "@type": "Audience",
      "audienceType": "EV owners, Energy analysts, Renewable energy professionals"
    },
    "api": {
      "endpoints": [
        {
          "path": "/api/rag/query",
          "method": "POST",
          "description": "Natural language query endpoint",
          "authentication": "Required (Clerk)"
        },
        {
          "path": "/api/fetch-stations",
          "method": "POST",
          "description": "EV charging station data",
          "authentication": "Required (Clerk)"
        },
        {
          "path": "/api/history/queries",
          "method": "GET",
          "description": "Query history",
          "authentication": "Required (Clerk)"
        },
        {
          "path": "/api/history/stats",
          "method": "GET",
          "description": "Usage statistics",
          "authentication": "Required (Clerk)"
        }
      ]
    },
    "dataSources": [
      "NREL Alternative Fuels Data Center API",
      "NREL PVWatts API",
      "OpenEI URDB API",
      "NREL REopt API"
    ],
    "rateLimits": {
      "free": "10 queries/month",
      "pro": "Unlimited queries"
    }
  }

  return NextResponse.json(aiMetadata, {
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET',
      'Cache-Control': 'public, max-age=3600, s-maxage=3600',
    },
  })
}

