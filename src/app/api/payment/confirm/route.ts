export const dynamic = 'force-dynamic';

export async function POST(req: Request) {
  const { booking_id, payment_id } = await req.json();
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  await fetch(`${url}/rest/v1/bookings?id=eq.${booking_id}`, {
    method: "PATCH",
    headers: {
      apikey: key!,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      status: "confirmed",
      payment_id: payment_id,
    }),
  });

  return Response.json({ success: true });
}
