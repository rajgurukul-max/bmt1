export const dynamic = 'force-dynamic';

export async function GET() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  const res = await fetch(
  `${url}/rest/v1/venues?is_active=eq.true&select=*&order=created_at.asc`,
  {
    headers: {
      apikey: key!,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    cache: "no-store",
  }
);

  const data = await res.json();
  return Response.json(data);
}
