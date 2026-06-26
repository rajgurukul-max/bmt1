import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const isLoginPage = request.nextUrl.pathname === "/login";
  
  // Log all cookies to find the right name
  const cookies = request.cookies.getAll();
  const cookieNames = cookies.map(c => c.name).join(", ");
  
  // For now just allow everything but add header to see cookies
  const response = NextResponse.next();
  response.headers.set("x-cookies", cookieNames);
  return response;
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
