export function StructuredData() {
  const baseUrl = process.env.NEXT_PUBLIC_BASE_URL || 'https://voltquery.ai'
  
  const websiteSchema = {
    "@context": "https://schema.org",
    "@type": "WebApplication",
    "name": "Volt Query AI",
    "description": "AI-powered insights for EV charging stations, electricity rates, solar energy production, and energy system optimization",
    "url": baseUrl,
    "applicationCategory": "UtilityApplication",
    "operatingSystem": "Web",
    "softwareVersion": "1.0.0",
    "browserRequirements": "Requires JavaScript. Requires HTML5.",
    "offers": {
      "@type": "Offer",
      "price": "0",
      "priceCurrency": "USD",
      "availability": "https://schema.org/InStock"
    },
    "featureList": [
      "EV charging station finder",
      "Electricity rate queries",
      "Solar energy production estimates",
      "Energy system optimization",
      "AI-powered natural language queries",
      "RAG (Retrieval-Augmented Generation) system",
      "Location-based data retrieval"
    ],
    "aggregateRating": {
      "@type": "AggregateRating",
      "ratingValue": "4.5",
      "ratingCount": "1"
    }
  }

  const organizationSchema = {
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": "Volt Query AI",
    "url": baseUrl,
    "logo": `${baseUrl}/favicon.svg`,
    "description": "AI-powered insights for EV charging stations, electricity rates, solar energy production, and energy system optimization",
    "sameAs": [
      `${baseUrl}/ai.txt`
    ]
  }

  // AI Agent Discovery Schema
  const aiAgentSchema = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "name": "Volt Query AI",
    "applicationCategory": "UtilityApplication",
    "operatingSystem": "Web",
    "softwareVersion": "1.0.0",
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
    "dataCatalog": {
      "@type": "DataCatalog",
      "name": "NREL Alternative Fuels Data Center",
      "description": "EV charging station data from NREL API"
    },
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
    }
  }

  // Service Schema for API Discovery
  const serviceSchema = {
    "@context": "https://schema.org",
    "@type": "Service",
    "serviceType": "AI-Powered Query Service",
    "name": "Volt Query AI RAG Service",
    "description": "Retrieval-Augmented Generation service for EV infrastructure and energy data queries",
    "provider": {
      "@type": "Organization",
      "name": "Volt Query AI"
    },
    "areaServed": {
      "@type": "Country",
      "name": "United States"
    },
    "hasOfferCatalog": {
      "@type": "OfferCatalog",
      "name": "Query Services",
      "itemListElement": [
        {
          "@type": "Offer",
          "itemOffered": {
            "@type": "Service",
            "name": "EV Charging Station Queries"
          }
        },
        {
          "@type": "Offer",
          "itemOffered": {
            "@type": "Service",
            "name": "Electricity Rate Queries"
          }
        },
        {
          "@type": "Offer",
          "itemOffered": {
            "@type": "Service",
            "name": "Solar Energy Estimates"
          }
        },
        {
          "@type": "Offer",
          "itemOffered": {
            "@type": "Service",
            "name": "Energy Optimization Analysis"
          }
        }
      ]
    }
  }

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(websiteSchema) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(organizationSchema) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(aiAgentSchema) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(serviceSchema) }}
      />
    </>
  )
}

