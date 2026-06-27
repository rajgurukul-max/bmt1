import { Users } from "lucide-react";

export default function BookingList({ bookings }: { bookings: any[] }) {
  return (
    <div className="space-y-3">
      {bookings.map((b) => (
        <div key={b.id} className="flex items-center justify-between border-b border-[#1E3324] last:border-0 pb-3 last:pb-0">
          <div className="flex items-center gap-4">
            <div className={`w-1.5 h-10 rounded-full ${b.status === "confirmed" ? "bg-[#8BC34A]" : "bg-[#E8A33D]"}`} />
            <div>
              <p className="text-sm font-medium">
                {b.player_name || b.name || "Guest"}{" "}
                <span className="text-[#5C7066] font-mono text-xs ml-1">#{b.id?.substring(0, 8)}</span>
              </p>
              <p className="text-xs text-[#9FB0A3]">
                {b.venues?.name || b.venue || "Venue"} · {b.booking_date} · {b.hour}:00 · <Users size={11} className="inline -mt-0.5" /> {b.players} players
              </p>
            </div>
          </div>
          <div className="text-right">
            <p className="font-mono text-sm">₹{b.amount?.toLocaleString("en-IN")}</p>
            <p className={`text-xs ${b.status === "confirmed" ? "text-[#8BC34A]" : "text-[#E8A33D]"}`}>
              {b.status}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
