export const dynamic = 'force-dynamic';

export async function POST(req: Request) {
  const body = await req.json();
  const { amount, venue_name } = body;

  const keyId = process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID;
  const secret = process.env.RAZORPAY_SECRET;

  const credentials = Buffer.from(`${keyId}:${secret}`).toString('base64');

  const res = await fetch('https://api.razorpay.com/v1/orders', {
    method: 'POST',
    headers: {
      'Authorization': `Basic ${credentials}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      amount: amount * 100, // Razorpay takes amount in paise
      currency: 'INR',
      receipt: `receipt_${Date.now()}`,
      notes: { venue_name },
    }),
  });

  const order = await res.json();
  return Response.json(order);
}
