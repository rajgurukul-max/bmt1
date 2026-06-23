export const dynamic = 'force-dynamic';

export async function GET() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  
  return Response.json({ 
    hasUrl: !!url, 
    hasKey: !!key,
    urlPreview: url ? url.substring(0, 20) : 'MISSING',
    keyPreview: key ? key.substring(0, 10) : 'MISSING'
  });
}
