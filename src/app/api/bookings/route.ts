export const dynamic = 'force-dynamic';

export async function GET() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  const res = await fetch(
    `${url}/rest/v1/bookings?select=*,venues(name,area)&order=created_at.desc&limit=20`,
    {
      headers: {
        apikey: key!,
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
      },
    }
  );

  const data = await res.json();
  return Response.json(data);
}

