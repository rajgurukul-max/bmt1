export const dynamic = 'force-dynamic';

export async function GET() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  
  if (!url || !key) {
    return Response.json({ error: 'Missing env vars', url: !!url, key: !!key });
  }

  const res = await fetch(`${url}/rest/v1/venues?is_active=eq.true&select=*`, {
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
    },
  });

  const data = await res.json();
  return Response.json(data);
}

