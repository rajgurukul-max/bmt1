export const dynamic = 'force-dynamic';

export async function POST(req: Request) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const body = await req.json();

  // First block the slot
  await fetch(`${url}/rest/v1/slots`, {
    method: "POST",
    headers: {
      apikey: key!,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
    },
    body: JSON.stringify({
      venue_id: body.venue_id,
      date: body.date,
      hour: body.hour,
      status: "booked",
    }),
  });

  // Then create booking
  const res = await fetch(`${url}/rest/v1/bookings`, {
    method: "POST",
    headers: {
      apikey: key!,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
    },
    body: JSON.stringify(body),
  });

  const data = await res.json();
  return Response.json(data);
}
