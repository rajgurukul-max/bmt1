import { Users } from "lucide-react";
import { Booking } from "@/lib/data";

export default function BookingList({ bookings }: { bookings: Booking[] }) {
  return (
    <div className="space-y-3">
      {bookings.map((b) => (
        <div
          key={b.id}
          className="flex items-center justify-between border-b border-pitch-border last:border-0 pb-3 last:pb-0"
        >
          <div className="flex items-center gap-4">
            <div
              className={`w-1.5 h-10 rounded-full ${
                b.status === "confirmed" ? "bg-turf" : "bg-amber"
              }`}
            />
            <div>
              <p className="text-sm font-medium">
                {b.name}{" "}
                <span className="text-dim font-mono text-xs ml-1">#{b.id}</span>
              </p>
              <p className="text-xs text-muted">
                {b.venue} · {b.date}, {b.time} ·{" "}
                <Users size={11} className="inline -mt-0.5" /> {b.players} players
              </p>
            </div>
          </div>
          <div className="text-right">
            <p className="font-mono text-sm">₹{b.amount.toLocaleString("en-IN")}</p>
            <p className={`text-xs ${b.status === "confirmed" ? "text-turf" : "text-amber"}`}>
              {b.status}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
