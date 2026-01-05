"use client"

import { useUser, UserButton } from "@clerk/nextjs"
import Link from "next/link"
import { Zap, History, CreditCard } from "lucide-react"
import { Button } from "@/components/ui/button"

export function AppHeader() {
  const { isSignedIn } = useUser()

  return (
    <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-50">
      <div className="container mx-auto px-4 py-4">
        <div className="flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Zap className="h-6 w-6 text-primary" />
            <span className="text-xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              Volt Query AI
            </span>
          </Link>

          <div className="flex items-center gap-4">
            {isSignedIn && (
              <>
                <Link href="/history">
                  <Button variant="ghost" className="gap-2">
                    <History className="h-4 w-4" />
                    History
                  </Button>
                </Link>
                <Link href="/subscription">
                  <Button variant="ghost" className="gap-2">
                    <CreditCard className="h-4 w-4" />
                    Subscription
                  </Button>
                </Link>
                <UserButton 
                  afterSignOutUrl="/"
                  appearance={{
                    variables: {
                      colorPrimary: "hsl(217 91% 60%)",
                      colorBackground: "hsl(222 47% 8%)",
                      colorInputBackground: "hsl(217 32% 17%)",
                      colorInputText: "hsl(210 40% 98%)",
                      colorText: "hsl(210 40% 98%)",
                      colorTextSecondary: "hsl(215 20% 65%)",
                      colorTextOnPrimaryBackground: "hsl(222 47% 8%)",
                      colorDanger: "hsl(0 84% 60%)",
                      colorSuccess: "hsl(142 76% 36%)",
                    },
                    elements: {
                      avatarBox: "w-10 h-10",
                      card: "bg-card border border-border shadow-lg",
                      cardBox: "bg-card border border-border",
                      headerTitle: "text-foreground",
                      headerSubtitle: "text-muted-foreground",
                      userButtonPopoverCard: "bg-card border border-border shadow-lg",
                      userButtonPopoverActions: "bg-card",
                      userButtonPopoverActionButton: "text-foreground hover:bg-secondary hover:text-foreground [&:hover]:text-foreground",
                      userButtonPopoverActionButtonText: "text-foreground [&:hover]:text-foreground",
                      userButtonPopoverActionButtonIcon: "text-foreground [&:hover]:text-foreground",
                      userButtonPopoverFooter: "text-muted-foreground",
                      userPreview: "text-foreground",
                      userPreviewTextContainer: "text-foreground",
                      userPreviewMainIdentifier: "text-foreground",
                      userPreviewSecondaryIdentifier: "text-muted-foreground",
                      userButtonMenu: "bg-card border border-border",
                      userButtonMenuItem: "text-foreground hover:bg-secondary [&:hover]:text-foreground",
                      userButtonMenuItemText: "text-foreground [&:hover]:text-foreground",
                      userButtonMenuItemIcon: "text-foreground [&:hover]:text-foreground",
                      userButtonTrigger: "text-foreground",
                      userButtonBox: "text-foreground",
                    },
                  }}
                />
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}

