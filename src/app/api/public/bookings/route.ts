export const dynamic = 'force-dynamic';

export async function POST(req: Request) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  
  try {
    const body = await req.json();
    console.log("Booking request:", JSON.stringify(body));

    // First block the slot
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
    console.log("Slot result:", JSON.stringify(slotData));

    // Then create booking
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
      }),
    });
    
    const bookingData = await bookingRes.json();
    console.log("Booking result:", JSON.stringify(bookingData));
    
    return Response.json(bookingData);
  } catch (e: any) {
    console.error("Booking error:", e.message);
    return Response.json({ error: e.message }, { status: 500 });
  }
}

