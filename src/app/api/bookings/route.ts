export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const authHeader = req.headers.get('authorization');
  const token = authHeader?.replace('Bearer ', '') || key;

  // Get owner's venues
  const venuesRes = await fetch(
    `${url}/rest/v1/venues?is_active=eq.true&select=id`,
    {
      headers: {
        apikey: key!,
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    }
  );
  const venues = await venuesRes.json();

  if (!Array.isArray(venues) || venues.length === 0) {
    return Response.json([]);
  }

  const venueIds = venues.map((v: any) => v.id).join(",");

  // Get bookings using service key to bypass RLS
  const bookingsRes = await fetch(
    `${url}/rest/v1/bookings?venue_id=in.(${venueIds})&select=*&order=created_at.desc&limit=50`,
    {
      headers: {
        apikey: key!,
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
      },
    }
  );

  const data = await bookingsRes.json();
  return Response.json(Array.isArray(data) ? data : []);
}
