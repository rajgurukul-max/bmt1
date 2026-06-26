import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const isLoginPage = request.nextUrl.pathname === "/login";
  
  const cookies = request.cookies.getAll();
  const hasAuth = cookies.some(
    (cookie) =>
      cookie.name.includes("sb-") &&
      cookie.name.includes("auth-token")
  );

  if (!hasAuth && !isLoginPage) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (hasAuth && isLoginPage) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
