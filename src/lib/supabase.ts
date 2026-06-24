export function getSupabase() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

  return {
    from: (table: string) => ({
      select: async (query = "*") => {
        const res = await fetch(
          `${url}/rest/v1/${table}?select=${query}`,
          {
            headers: {
              apikey: key,
              Authorization: `Bearer ${key}`,
            },
          }
        );
        return res.json();
      },
    }),
  };
}
