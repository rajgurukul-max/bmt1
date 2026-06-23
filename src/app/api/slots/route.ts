import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const venue_id = searchParams.get("venue_id");
  const date = searchParams.get("date");

  const { data, error } = await supabase
    .from("slots")
    .select("*")
    .eq("venue_id", venue_id)
    .eq("date", date);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(req: Request) {
  const body = await req.json();
  const { venue_id, date, hour, status } = body;

  const { data: existing } = await supabase
    .from("slots")
    .select("*")
    .eq("venue_id", venue_id)
    .eq("date", date)
    .eq("hour", hour)
    .single();

  if (existing) {
    const { data, error } = await supabase
      .from("slots")
      .update({ status })
      .eq("id", existing.id)
      .select();

    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    return NextResponse.json(data);
  }

  const { data, error } = await supabase
    .from("slots")
    .insert([{ venue_id, date, hour, status }])
    .select();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}
