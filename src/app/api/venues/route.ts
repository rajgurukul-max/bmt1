export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // Get auth token from request header
  const authHeader = req.headers.get('authorization');
  const token = authHeader?.replace('Bearer ', '') || key;

  const res = await fetch(
    `${url}/rest/v1/venues?is_active=eq.true&select=*&order=created_at.asc`,
    {
      headers: {
        apikey: key!,
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    }
  );

  const data = await res.json();
  return Response.json(data);
}

export async function POST(req: Request) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const authHeader = req.headers.get('authorization');
  const token = authHeader?.replace('Bearer ', '') || key;
  
  const body = await req.json();

  const res = await fetch(`${url}/rest/v1/venues`, {
    method: "POST",
    headers: {
      apikey: key!,
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
    },
    body: JSON.stringify(body),
  });

  const data = await res.json();
  return Response.json(data);
}
