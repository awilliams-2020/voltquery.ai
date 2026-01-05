import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

const isPublicRoute = createRouteMatcher([
  "/",
  "/api/webhooks(.*)",
  "/sign-in(.*)",
  "/sign-up(.*)",
  "/sitemap.xml",
  "/sitemap(.*)",
  "/robots.txt",
  "/robots(.*)",
  "/ai.txt",
  "/api/ai-metadata",
  "/opengraph-image(.*)",
  "/icon(.*)",
  "/favicon(.*)",
  "/apple-touch-icon(.*)",
  "/site.webmanifest",
]);

export default clerkMiddleware(async (auth, request) => {
  if (!isPublicRoute(request)) {
    const { userId } = await auth();
    if (!userId) {
      const signInUrl = new URL("/sign-in", request.url);
      signInUrl.searchParams.set("redirect_url", request.url);
      return NextResponse.redirect(signInUrl);
    }
  }
  return NextResponse.next();
});

export const config = {
  matcher: [
    // Skip Next.js internals, static files, and public metadata files
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)|sitemap|robots|ai\\.txt|opengraph-image|icon|favicon|apple-touch-icon|site\\.webmanifest).*)",
    // Always run for API routes (except public metadata endpoints)
    "/api/:path*",
    "/trpc/:path*",
  ],
};

