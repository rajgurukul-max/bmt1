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
