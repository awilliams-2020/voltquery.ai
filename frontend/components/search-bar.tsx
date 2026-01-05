"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Search } from "lucide-react"

interface SearchBarProps {
  onSearch: (zipCode: string) => void
  loading?: boolean
}

export function SearchBar({ onSearch, loading = false }: SearchBarProps) {
  const [zipCode, setZipCode] = useState("")

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (zipCode.trim()) {
      onSearch(zipCode.trim())
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <div className="flex-1 relative">
        <Input
          type="text"
          placeholder="Enter zip code (e.g., 80202)"
          value={zipCode}
          onChange={(e) => setZipCode(e.target.value)}
          disabled={loading}
          className="pl-10"
          maxLength={5}
          pattern="[0-9]{5}"
        />
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
      </div>
      <Button type="submit" disabled={loading || !zipCode.trim()}>
        {loading ? "Searching..." : "Search"}
      </Button>
    </form>
  )
}

