export const dynamic = 'force-dynamic';

export async function POST(req: Request) {
  const { booking_id, payment_id } = await req.json();
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // Update booking status
  const res = await fetch(`${url}/rest/v1/bookings?id=eq.${booking_id}`, {
    method: "PATCH",
    headers: {
      apikey: key!,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
    },
    body: JSON.stringify({
      status: "confirmed",
      payment_id: payment_id,
    }),
  });
  const bookings = await res.json();
  const booking = bookings?.[0];

  if (booking) {
    // Get venue and owner details
    const venueRes = await fetch(
      `${url}/rest/v1/venues?id=eq.${booking.venue_id}&select=*`,
      {
        headers: {
          apikey: key!,
          Authorization: `Bearer ${key}`,
        },
      }
    );
    const venues = await venueRes.json();
    const venue = venues?.[0];

    // Get owner email
    const ownerRes = await fetch(
      `${url}/rest/v1/owners?id=eq.${venue?.owner_id}&select=email`,
      {
        headers: {
          apikey: key!,
          Authorization: `Bearer ${key}`,
        },
      }
    );
    const owners = await ownerRes.json();
    const ownerEmail = owners?.[0]?.email;

    // Send notification
    console.log("Owner email found:", ownerEmail);
    console.log("Sending notification...");
    if (ownerEmail) {

      await fetch(`https://www.bookmyturfs.com/api/notify/booking`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          owner_email: ownerEmail,
          player_name: booking.player_name,
          player_phone: booking.player_phone,
          venue_name: venue?.name,
          booking_date: booking.booking_date,
          hour: booking.hour,
          amount: booking.amount,
          players: booking.players,
        }),
      });
    }
  }

  return Response.json({ success: true });
}
