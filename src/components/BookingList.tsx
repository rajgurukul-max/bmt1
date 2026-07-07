import { Users, Tag } from "lucide-react";

export default function BookingList({ bookings }: { bookings: any[] }) {
  const groups = bookings.reduce((acc: Record<string, any[]>, b: any) => {
    const key = b.booking_group_id || b.id;
    if (!acc[key]) acc[key] = [];
    acc[key].push(b);
    return acc;
  }, {} as Record<string, any[]>);

  const groupedBookings = Object.values(groups).map((rows) => {
    const first = rows[0];
    const hours = rows.map((r) => r.hour).sort((a, b) => a - b);
    const totalAmount = rows.reduce((sum, r) => sum + (r.amount || 0), 0);
    const totalDiscount = rows.reduce((sum, r) => sum + (r.discount_applied || 0), 0);
    const promoCode = rows.find((r) => r.promo_code)?.promo_code;
    const allConfirmed = rows.every((r) => r.status === "confirmed");

    return {
      id: first.id,
      player_name: first.player_name || first.name || "Guest",
      venueName: first.venues?.name || first.venue || "Venue",
      date: first.booking_date,
      hours,
      players: first.players,
      totalAmount,
      totalDiscount,
      promoCode,
      status: allConfirmed ? "confirmed" : first.status,
      count: rows.length,
    };
  });

  return (
    <div className="space-y-3">
      {groupedBookings.map((g) => (
        <div
          key={g.id}
          className="flex items-center justify-between border-b border-[#1E3324] last:border-0 pb-3 last:pb-0"
        >
          <div className="flex items-center gap-4">
            <div
              className={`w-1.5 h-10 rounded-full ${
                g.status === "confirmed" ? "bg-[#8BC34A]" : "bg-[#E8A33D]"
              }`}
            />
            <div>
              <p className="text-sm font-medium">
                {g.player_name}{" "}
                <span className="text-[#5C7066] font-mono text-xs ml-1">
                  #{g.id?.substring(0, 8)}
                </span>
                {g.count > 1 && (
                  <span className="text-[#8BC34A] text-xs ml-2 bg-[#8BC34A]/10 px-2 py-0.5 rounded-full">
                    {g.count} slots
                  </span>
                )}
              </p>
              <p className="text-xs text-[#9FB0A3]">
                {g.venueName} · {g.date} · {g.hours.map((h: number) => `${h}:00`).join(", ")} ·{" "}
                <Users size={11} className="inline -mt-0.5" /> {g.players} players
              </p>
              {g.promoCode && (
                <p className="text-xs text-[#8BC34A] mt-0.5 flex items-center gap-1">
                  <Tag size={10} /> {g.promoCode} applied · ₹{g.totalDiscount.toLocaleString("en-IN")} off
                </p>
              )}
            </div>
          </div>
          <div className="text-right">
            <p className="font-mono text-sm">₹{g.totalAmount?.toLocaleString("en-IN")}</p>
            <p
              className={`text-xs ${
                g.status === "confirmed" ? "text-[#8BC34A]" : "text-[#E8A33D]"
              }`}
            >
              {g.status}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
