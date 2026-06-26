import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const isLoginPage = request.nextUrl.pathname === "/login";
  const isBookPage = request.nextUrl.pathname.startsWith("/book");
  const isPublicApi = request.nextUrl.pathname.startsWith("/api/public");

  // Allow public access to booking pages
  if (isBookPage || isPublicApi) {
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
