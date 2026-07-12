"use client";
import { MapPin } from "lucide-react";
import { HOURS, dateLabel, SlotStatus } from "@/lib/data";

const STATUS_STYLE: Record<SlotStatus, string> = {
  open: "bg-[#16291C] border border-[#2C4A33] text-[#8BC34A] hover:border-[#8BC34A] cursor-pointer",
  booked: "bg-[#8BC34A] border border-[#8BC34A] text-[#0E1F14] font-semibold cursor-default",
  blocked: "bg-[#E5484D]/20 border border-[#E5484D]/50 text-[#E5484D] cursor-pointer",
};

export default function SlotCalendar({ activeVenue, onVenueChange, days, activeDay, onDayChange, slots, onToggleSlot, venues }:
  { activeVenue: string; onVenueChange: (id: string) => void; days: Date[]; activeDay: number; onDayChange: (i: number) => void; slots: Record<string, SlotStatus>; onToggleSlot: (hour: number) => void; venues: any[] }) {
  const venue = venues.find((v) => v.id === activeVenue);
  const day = days[activeDay];
  return (
    <>
      <div className="flex gap-2 mb-4 flex-wrap">
        {venues.map((v) => (
          <button key={v.id} onClick={() => onVenueChange(v.id)}
            className={`px-4 py-2 rounded-md text-sm border transition-colors ${
              activeVenue === v.id ? "bg-[#8BC34A] text-[#0E1F14] border-[#8BC34A] font-medium" : "border-[#2C4A33] text-[#9FB0A3] hover:border-[#8BC34A]"
            }`}>
            <MapPin size={13} className="inline mr-1.5 -mt-0.5" />{v.name}
          </button>
        ))}
      </div>
      <div className="flex gap-2 mb-6">
        {days.map((d, i) => (
          <button key={i} onClick={() => onDayChange(i)}
            className={`px-3 py-1.5 rounded text-xs font-mono ${
              activeDay === i ? "bg-[#1E3324] text-[#8BC34A] border border-[#8BC34A]" : "text-[#9FB0A3] border border-transparent hover:border-[#2C4A33]"
            }`}>
            {dateLabel(d)}
          </button>
        ))}
      </div>
      <div className="bg-[#16291C] border border-[#1E3324] rounded-lg p-6">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <p className="text-sm text-[#9FB0A3]">{venue?.name} — tap a slot to block / unblock</p>
          <div className="flex gap-4 text-xs">
            {[["bg-[#16291C] border border-[#2C4A33]","Open"],["bg-[#8BC34A]","Booked"],["bg-[#E5484D]/30","Blocked"]].map(([color,label])=>(
              <div key={label} className="flex items-center gap-1.5 text-[#9FB0A3]">
                <span className={`w-3 h-3 rounded-sm ${color}`}/>{label}
              </div>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-7 gap-2">
          {HOURS.map((h) => {
            const key = `${activeVenue}_${day.toDateString()}_${h}`;
            const st = slots[key] ?? "open";
            return (
              <button key={h} onClick={() => onToggleSlot(h)}
                className={`rounded-md py-3 text-xs font-mono text-center transition-colors ${STATUS_STYLE[st]}`}>
                {(h % 24) % 12 === 0 ? 12 : (h % 24) % 12}:00 {(h % 24) < 12 ? "AM" : "PM"}
              </button>
            );
          })}
        </div>
      </div>
    </>
  );
}
