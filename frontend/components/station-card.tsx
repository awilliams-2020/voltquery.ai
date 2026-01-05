"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { MapPin, Zap, Battery } from "lucide-react"

interface Station {
  station_name?: string
  street_address?: string
  city?: string
  state?: string
  zip?: string
  ev_network?: string
  ev_connector_types?: string[]
  ev_dc_fast_num?: number
  ev_level2_evse_num?: number
  latitude?: number
  longitude?: number
}

interface StationCardProps {
  station: Station
}

export function StationCard({ station }: StationCardProps) {
  const address = [
    station.street_address,
    station.city,
    station.state,
    station.zip,
  ]
    .filter(Boolean)
    .join(", ")

  const connectors = station.ev_connector_types?.join(", ") || "N/A"
  const dcFast = station.ev_dc_fast_num || 0
  const level2 = station.ev_level2_evse_num || 0

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Zap className="h-5 w-5 text-blue-600" />
          {station.station_name || "Unnamed Station"}
        </CardTitle>
        <CardDescription className="flex items-center gap-1">
          <MapPin className="h-4 w-4" />
          {address || "Address not available"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {station.ev_network && (
            <div>
              <span className="text-sm font-medium">Network: </span>
              <span className="text-sm text-muted-foreground">
                {station.ev_network}
              </span>
            </div>
          )}
          <div>
            <span className="text-sm font-medium">Connector Types: </span>
            <span className="text-sm text-muted-foreground">{connectors}</span>
          </div>
          <div className="flex gap-4 pt-2">
            {dcFast > 0 && (
              <div className="flex items-center gap-1">
                <Battery className="h-4 w-4 text-orange-600" />
                <span className="text-sm">
                  <span className="font-medium">{dcFast}</span> DC Fast
                </span>
              </div>
            )}
            {level2 > 0 && (
              <div className="flex items-center gap-1">
                <Zap className="h-4 w-4 text-blue-600" />
                <span className="text-sm">
                  <span className="font-medium">{level2}</span> Level 2
                </span>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

