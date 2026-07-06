import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET() {
  const { data, error } = await supabase
    .from("promo_codes")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(req: Request) {
  const body = await req.json();

  const {
    code,
    discount_type,
    discount_value,
    min_amount,
    max_uses,
    expires_at,
  } = body;

  if (!code || !discount_type || !discount_value) {
    return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
  }

  const { data, error } = await supabase
    .from("promo_codes")
    .insert([
      {
        code: code.toUpperCase().trim(),
        discount_type,
        discount_value: Number(discount_value),
        min_amount: min_amount ? Number(min_amount) : 0,
        max_uses: max_uses ? Number(max_uses) : null,
        expires_at: expires_at || null,
        is_active: true,
      },
    ])
    .select();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function PATCH(req: Request) {
  const body = await req.json();
  const { id, is_active } = body;

  if (!id) return NextResponse.json({ error: "Missing id" }, { status: 400 });

  const { data, error } = await supabase
    .from("promo_codes")
    .update({ is_active })
    .eq("id", id)
    .select();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

