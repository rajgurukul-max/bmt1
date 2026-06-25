import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const code = requestUrl.searchParams.get("code");

  if (code) {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
    const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

    await fetch(`${supabaseUrl}/auth/v1/token?grant_type=pkce`, {
      method: "POST",
      headers: {
        apikey: supabaseKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ auth_code: code }),
    });
  }

  return NextResponse.redirect(new URL("/", request.url));
}
