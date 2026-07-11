export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

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

  const userRes = await fetch(`${url}/auth/v1/user`, {
    headers: {
      apikey: key!,
      Authorization: `Bearer ${token}`,
    },
  });
  const user = await userRes.json();

  const res = await fetch(`${url}/rest/v1/venues`, {
    method: "POST",
    headers: {
      apikey: key!,
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
    },
    body: JSON.stringify({
      ...body,
      owner_id: user?.id || body.owner_id,
    }),
  });

  const data = await res.json();
  return Response.json(data);
}

export async function PATCH(req: Request) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const authHeader = req.headers.get('authorization');
  const token = authHeader?.replace('Bearer ', '') || key;

  const body = await req.json();
  const { id, ...fields } = body;

  if (!id) {
    return Response.json({ error: "Missing venue id" }, { status: 400 });
  }

  const res = await fetch(`${url}/rest/v1/venues?id=eq.${id}`, {
    method: "PATCH",
    headers: {
      apikey: key!,
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
    },
    body: JSON.stringify(fields),
  });

  const data = await res.json();
  return Response.json(data);
}
