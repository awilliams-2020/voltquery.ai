export default function AuthLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background to-[hsl(222_47%_6%)] px-2 sm:px-4 py-8">
      <div className="w-full max-w-md">
        {children}
      </div>
    </div>
  )
}

