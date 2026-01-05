export default function AuthLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background to-[hsl(222_47%_6%)]">
      {children}
    </div>
  )
}

