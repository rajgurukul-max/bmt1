export const dynamic = 'force-dynamic';

export async function POST(req: Request) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  try {
    const body = await req.json();
    // Reject bookings for time slots that have already passed today (IST)
const istNow = new Date(Date.now() + 5.5 * 60 * 60 * 1000);
const istDateStr = istNow.toISOString().split("T")[0];
const istHour = istNow.getUTCHours();
if (body.date === istDateStr && Number(body.hour) <= istHour) {
  return Response.json({ error: "This time slot has already passed" }, { status: 400 });
}

    // Block the slot
    const slotRes = await fetch(`${url}/rest/v1/slots`, {
      method: "POST",
      headers: {
        apikey: key!,
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
        Prefer: "return=representation,resolution=merge-duplicates",
      },
      body: JSON.stringify({
        venue_id: body.venue_id,
        date: body.date,
        hour: body.hour,
        status: "booked",
      }),
    });
    const slotData = await slotRes.json();

    // Create booking
    const bookingRes = await fetch(`${url}/rest/v1/bookings`, {
      method: "POST",
      headers: {
        apikey: key!,
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify({
        venue_id: body.venue_id,
        slot_id: slotData?.[0]?.id || null,
        player_name: body.player_name,
        player_phone: body.player_phone,
        players: body.players || 1,
        amount: body.amount,
        status: body.status || "pending",
        payment_id: body.payment_id || "",
        booking_date: body.booking_date,
        hour: body.hour,
        booking_group_id: body.booking_group_id || null,
        promo_code: body.promo_code || null,
        discount_applied: body.discount_applied || 0,
        discount_type: body.discount_type || null,
      }),
    });
    const bookingData = await bookingRes.json();

    // Get venue and owner details for notification
    const venueRes = await fetch(
      `${url}/rest/v1/venues?id=eq.${body.venue_id}&select=*,owners(email)`,
      {
        headers: {
          apikey: key!,
          Authorization: `Bearer ${key}`,
        },
      }
    );
    const venues = await venueRes.json();
    const venue = venues?.[0];

    // Get owner email from auth.users
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

    // Send email notification if owner email found
    if (ownerEmail && body.status === "confirmed") {
      await fetch(`${process.env.NEXT_PUBLIC_APP_URL || 'https://www.bookmyturfs.com'}/api/notify/booking`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          owner_email: ownerEmail,
          player_name: body.player_name,
          player_phone: body.player_phone,
          venue_name: venue?.name,
          booking_date: body.booking_date,
          hour: body.hour,
          amount: body.amount,
          players: body.players,
        }),
      });
    }

    return Response.json(bookingData);
  } catch (e: any) {
    return Response.json({ error: e.message }, { status: 500 });
  }
}
