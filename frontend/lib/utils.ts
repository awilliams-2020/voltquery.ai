import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"
import React from "react"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Simple markdown parser that converts basic markdown to React elements
 * Handles: bold (**text**), headings (###), lists (- or 1.), and line breaks
 */
export function parseMarkdown(text: string): React.ReactNode[] {
  if (!text) return []
  
  const lines = text.split('\n')
  const elements: React.ReactNode[] = []
  let currentList: React.ReactNode[] = []
  let listType: 'ul' | 'ol' | null = null
  
  const processLine = (line: string, index: number) => {
    const trimmed = line.trim()
    
    // Empty line - close any open list
    if (!trimmed) {
      if (currentList.length > 0 && listType) {
        const ListTag = listType === 'ul' ? 'ul' : 'ol'
        elements.push(
          React.createElement(ListTag, { key: `list-${index}`, className: listType === 'ul' ? 'list-disc list-inside space-y-1 my-2 ml-4' : 'list-decimal list-inside space-y-1 my-2 ml-4' }, ...currentList)
        )
        currentList = []
        listType = null
      }
      elements.push(React.createElement('br', { key: `br-${index}` }))
      return
    }
    
    // Headings
    if (trimmed.startsWith('### ')) {
      if (currentList.length > 0 && listType) {
        const ListTag = listType === 'ul' ? 'ul' : 'ol'
        elements.push(
          React.createElement(ListTag, { key: `list-${index}`, className: listType === 'ul' ? 'list-disc list-inside space-y-1 my-2 ml-4' : 'list-decimal list-inside space-y-1 my-2 ml-4' }, ...currentList)
        )
        currentList = []
        listType = null
      }
      const headingText = parseInlineMarkdown(trimmed.substring(4))
      elements.push(
        React.createElement('h3', { key: `h3-${index}`, className: 'text-lg font-semibold mt-4 mb-2' }, ...headingText)
      )
      return
    }
    
    if (trimmed.startsWith('## ')) {
      if (currentList.length > 0 && listType) {
        const ListTag = listType === 'ul' ? 'ul' : 'ol'
        elements.push(
          React.createElement(ListTag, { key: `list-${index}`, className: listType === 'ul' ? 'list-disc list-inside space-y-1 my-2 ml-4' : 'list-decimal list-inside space-y-1 my-2 ml-4' }, ...currentList)
        )
        currentList = []
        listType = null
      }
      const headingText = parseInlineMarkdown(trimmed.substring(3))
      elements.push(
        React.createElement('h2', { key: `h2-${index}`, className: 'text-xl font-semibold mt-4 mb-2' }, ...headingText)
      )
      return
    }
    
    if (trimmed.startsWith('# ')) {
      if (currentList.length > 0 && listType) {
        const ListTag = listType === 'ul' ? 'ul' : 'ol'
        elements.push(
          React.createElement(ListTag, { key: `list-${index}`, className: listType === 'ul' ? 'list-disc list-inside space-y-1 my-2 ml-4' : 'list-decimal list-inside space-y-1 my-2 ml-4' }, ...currentList)
        )
        currentList = []
        listType = null
      }
      const headingText = parseInlineMarkdown(trimmed.substring(2))
      elements.push(
        React.createElement('h1', { key: `h1-${index}`, className: 'text-2xl font-bold mt-4 mb-2' }, ...headingText)
      )
      return
    }
    
    // Unordered list
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      if (listType === 'ol') {
        const ListTag = 'ol'
        elements.push(
          React.createElement(ListTag, { key: `list-${index}`, className: 'list-decimal list-inside space-y-1 my-2 ml-4' }, ...currentList)
        )
        currentList = []
      }
      listType = 'ul'
      const itemText = parseInlineMarkdown(trimmed.substring(2))
      currentList.push(
        React.createElement('li', { key: `li-${index}` }, ...itemText)
      )
      return
    }
    
    // Ordered list
    const orderedMatch = trimmed.match(/^(\d+)\.\s+(.+)$/)
    if (orderedMatch) {
      if (listType === 'ul') {
        const ListTag = 'ul'
        elements.push(
          React.createElement(ListTag, { key: `list-${index}`, className: 'list-disc list-inside space-y-1 my-2 ml-4' }, ...currentList)
        )
        currentList = []
      }
      listType = 'ol'
      const itemText = parseInlineMarkdown(orderedMatch[2])
      currentList.push(
        React.createElement('li', { key: `li-${index}` }, ...itemText)
      )
      return
    }
    
    // Regular paragraph
    if (currentList.length > 0 && listType) {
      const ListTag = listType === 'ul' ? 'ul' : 'ol'
      elements.push(
        React.createElement(ListTag, { key: `list-${index}`, className: listType === 'ul' ? 'list-disc list-inside space-y-1 my-2 ml-4' : 'list-decimal list-inside space-y-1 my-2 ml-4' }, ...currentList)
      )
      currentList = []
      listType = null
    }
    
    const paragraphText = parseInlineMarkdown(trimmed)
    elements.push(
      React.createElement('p', { key: `p-${index}`, className: 'mb-2' }, ...paragraphText)
    )
  }
  
  lines.forEach((line, index) => processLine(line, index))
  
  // Close any remaining list
  if (currentList.length > 0 && listType) {
    const ListTag = listType === 'ul' ? 'ul' : 'ol'
    elements.push(
      React.createElement(ListTag, { key: 'list-final', className: listType === 'ul' ? 'list-disc list-inside space-y-1 my-2 ml-4' : 'list-decimal list-inside space-y-1 my-2 ml-4' }, ...currentList)
    )
  }
  
  return elements
}

/**
 * Parse inline markdown (bold, italic, etc.)
 */
function parseInlineMarkdown(text: string): React.ReactNode[] {
  if (!text) return []
  
  const parts: React.ReactNode[] = []
  
  // Match bold: **text**
  const boldRegex = /\*\*(.+?)\*\*/g
  let match
  let lastIndex = 0
  let keyCounter = 0
  
  while ((match = boldRegex.exec(text)) !== null) {
    // Add text before the match
    if (match.index > lastIndex) {
      const beforeText = text.substring(lastIndex, match.index)
      if (beforeText) {
        parts.push(beforeText)
      }
    }
    
    // Add bold text
    parts.push(
      React.createElement('strong', { key: `bold-${keyCounter++}` }, match[1])
    )
    
    lastIndex = match.index + match[0].length
  }
  
  // Add remaining text
  if (lastIndex < text.length) {
    const remainingText = text.substring(lastIndex)
    if (remainingText) {
      parts.push(remainingText)
    }
  }
  
  // If no parts were created (no bold text found), return the original text
  return parts.length > 0 ? parts : [text]
}

