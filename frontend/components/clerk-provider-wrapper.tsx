"use client"

import { ClerkProvider as ClerkProviderBase } from "@clerk/nextjs"
import { ReactNode } from "react"

interface ClerkProviderWrapperProps {
  children: ReactNode
}

export function ClerkProviderWrapper({ children }: ClerkProviderWrapperProps) {
  return (
    <ClerkProviderBase
      appearance={{
        variables: {
          colorPrimary: "hsl(217 91% 60%)",
          colorBackground: "hsl(222 47% 8%)",
          colorInputBackground: "hsl(217 32% 17%)",
          colorInputText: "hsl(210 40% 98%)",
          colorText: "hsl(210 40% 98%)",
          colorTextSecondary: "hsl(215 20% 65%)",
          colorTextOnPrimaryBackground: "hsl(222 47% 8%)",
          colorShimmer: "hsl(217 32% 20%)",
          colorNeutral: "hsl(217 32% 17%)",
          colorSuccess: "hsl(142 76% 36%)",
          colorWarning: "hsl(38 92% 50%)",
          colorDanger: "hsl(0 84% 60%)",
        },
        elements: {
          formButtonPrimary: "bg-primary hover:bg-primary/90 text-primary-foreground",
          card: "bg-card border border-border",
          headerTitle: "text-foreground",
          headerSubtitle: "text-muted-foreground",
          socialButtonsBlockButton: "border-border bg-secondary hover:bg-secondary/80 text-secondary-foreground",
          formFieldInput: "bg-input border-input text-foreground",
          formFieldLabel: "text-foreground",
          formFieldSuccessText: "text-success",
          formFieldErrorText: "text-destructive",
          formFieldWarningText: "text-warning",
          formFieldHintText: "text-muted-foreground",
          identityPreviewText: "text-foreground",
          identityPreviewEditButton: "text-primary",
          footerActionLink: "text-primary",
          footerActionText: "text-muted-foreground",
          formResendCodeLink: "text-primary",
          otpCodeFieldInput: "bg-input border-input text-foreground",
          otpCodeFieldInputs: "bg-input border-input text-foreground",
        },
      }}
    >
      {children}
    </ClerkProviderBase>
  )
}

