export const dynamic = 'force-dynamic';

export async function POST(req: Request) {
  const body = await req.json();
  const {
    owner_email,
    player_name,
    player_phone,
    venue_name,
    booking_date,
    hour,
    amount,
    players,
  } = body;

  const apiKey = process.env.RESEND_API_KEY;

  const emailHtml = `
    <div style="font-family: sans-serif; max-width: 500px; margin: 0 auto; background: #0E1F14; color: #F4F7ED; padding: 32px; border-radius: 12px;">
      <div style="color: #8BC34A; font-size: 12px; letter-spacing: 4px; text-transform: uppercase; margin-bottom: 8px;">BookMyTurfs</div>
      <h1 style="font-size: 22px; margin: 0 0 24px;">New Booking! 🎉</h1>
      
      <div style="background: #16291C; border: 1px solid #1E3324; border-radius: 8px; padding: 20px; margin-bottom: 16px;">
        <p style="color: #9FB0A3; font-size: 12px; margin: 0 0 4px;">VENUE</p>
        <p style="font-size: 16px; font-weight: 600; margin: 0;">${venue_name}</p>
      </div>

      <div style="background: #16291C; border: 1px solid #1E3324; border-radius: 8px; padding: 20px; margin-bottom: 16px;">
        <p style="color: #9FB0A3; font-size: 12px; margin: 0 0 4px;">PLAYER</p>
        <p style="font-size: 16px; font-weight: 600; margin: 0 0 4px;">${player_name}</p>
        <p style="color: #9FB0A3; font-size: 14px; margin: 0;">📞 ${player_phone} · ${players} players</p>
      </div>

      <div style="background: #16291C; border: 1px solid #1E3324; border-radius: 8px; padding: 20px; margin-bottom: 16px;">
        <p style="color: #9FB0A3; font-size: 12px; margin: 0 0 4px;">DATE & TIME</p>
        <p style="font-size: 16px; font-weight: 600; margin: 0;">${booking_date} at ${hour}:00 ${hour < 12 ? 'AM' : 'PM'}</p>
      </div>

      <div style="background: #8BC34A; border-radius: 8px; padding: 20px; text-align: center;">
        <p style="color: #0E1F14; font-size: 12px; margin: 0 0 4px;">AMOUNT RECEIVED</p>
        <p style="color: #0E1F14; font-size: 28px; font-weight: 700; font-family: monospace; margin: 0;">₹${amount?.toLocaleString('en-IN')}</p>
      </div>

      <p style="color: #5C7066; font-size: 12px; text-align: center; margin-top: 24px;">
        Login to your dashboard at bookmyturfs.com to manage this booking.
      </p>
    </div>
  `;

  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: 'BookMyTurfs <notifications@bookmyturfs.com>',
      to: [owner_email],
      subject: `New booking at ${venue_name} — ₹${amount?.toLocaleString('en-IN')}`,
      html: emailHtml,
    }),
  });

  const data = await res.json();
  return Response.json(data);
}
