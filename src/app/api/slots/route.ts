export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const { searchParams } = new URL(req.url);
  const venue_id = searchParams.get("venue_id");
  const date = searchParams.get("date");

  const res = await fetch(
    `${url}/rest/v1/slots?venue_id=eq.${venue_id}&date=eq.${date}&select=*`,
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

export async function POST(req: Request) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const body = await req.json();
  const { venue_id, date, hour, status } = body;

  // Check if slot exists
  const checkRes = await fetch(
    `${url}/rest/v1/slots?venue_id=eq.${venue_id}&date=eq.${date}&hour=eq.${hour}&select=*`,
    {
      headers: {
        apikey: key!,
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
      },
    }
  );
  const existing = await checkRes.json();

  if (existing.length > 0) {
    // Update existing slot
    const updateRes = await fetch(
      `${url}/rest/v1/slots?id=eq.${existing[0].id}`,
      {
        method: "PATCH",
        headers: {
          apikey: key!,
          Authorization: `Bearer ${key}`,
          "Content-Type": "application/json",
          Prefer: "return=representation",
        },
        body: JSON.stringify({ status }),
      }
    );
    const data = await updateRes.json();
    return Response.json(data);
  }

  // Create new slot
  const insertRes = await fetch(`${url}/rest/v1/slots`, {
    method: "POST",
    headers: {
      apikey: key!,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
    },
    body: JSON.stringify({ venue_id, date, hour, status }),
  });

  const data = await insertRes.json();
  return Response.json(data);
}
