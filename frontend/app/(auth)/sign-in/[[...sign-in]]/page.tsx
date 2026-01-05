"use client"

import { SignIn } from "@clerk/nextjs"

export default function SignInPage() {
  return (
    <SignIn 
      appearance={{
        variables: {
          colorPrimary: "hsl(217 91% 60%)",
          colorBackground: "hsl(222 47% 8%)",
          colorInputBackground: "hsl(217 32% 17%)",
          colorInputText: "hsl(210 40% 98%)",
          colorText: "hsl(210 40% 98%)",
          colorTextSecondary: "hsl(215 20% 65%)",
          colorTextOnPrimaryBackground: "hsl(222 47% 8%)",
        },
        elements: {
          rootBox: "mx-auto",
          card: "bg-card border border-border shadow-lg",
          formButtonPrimary: "bg-primary hover:bg-primary/90 text-primary-foreground",
          headerTitle: "text-foreground",
          headerSubtitle: "text-muted-foreground",
          formFieldInput: "bg-input border-input text-foreground",
          formFieldLabel: "text-foreground",
          formFieldSuccessText: "text-success",
          formFieldErrorText: "text-destructive",
          formFieldHintText: "text-muted-foreground",
          footerActionLink: "text-primary",
          footerActionText: "text-muted-foreground",
          identityPreviewText: "text-foreground",
          identityPreviewEditButton: "text-primary",
          otpCodeFieldInput: "bg-input border-input text-foreground",
        },
      }}
      routing="path"
      path="/sign-in"
      signUpUrl="/sign-up"
    />
  )
}

