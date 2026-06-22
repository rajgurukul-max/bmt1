"use client";

import { MapPin } from "lucide-react";
import { VENUES, HOURS, dateLabel, SlotStatus } from "@/lib/data";

const STATUS_STYLE: Record<SlotStatus, string> = {
  open: "bg-pitch-surface border border-pitch-borderlight text-turf hover:border-turf cursor-pointer",
  booked: "bg-turf border border-turf text-pitch font-semibold cursor-default",
  blocked: "bg-danger/20 border border-danger/50 text-danger cursor-pointer",
};

export default function SlotCalendar({
  activeVenue,
  onVenueChange,
  days,
  activeDay,
  onDayChange,
  slots,
  onToggleSlot,
}: {
  activeVenue: string;
  onVenueChange: (id: string) => void;
  days: Date[];
  activeDay: number;
  onDayChange: (i: number) => void;
  slots: Record<string, SlotStatus>;
  onToggleSlot: (hour: number) => void;
}) {
  const venue = VENUES.find((v) => v.id === activeVenue)!;
  const day = days[activeDay];

  return (
    <>
      <div className="flex gap-2 mb-4 flex-wrap">
        {VENUES.map((v) => (
          <button
            key={v.id}
            onClick={() => onVenueChange(v.id)}
            className={`px-4 py-2 rounded-md text-sm border transition-colors ${
              activeVenue === v.id
                ? "bg-turf text-pitch border-turf font-medium"
                : "border-pitch-borderlight text-muted hover:border-turf"
            }`}
          >
            <MapPin size={13} className="inline mr-1.5 -mt-0.5" />
            {v.name}
          </button>
        ))}
      </div>

      <div className="flex gap-2 mb-6">
        {days.map((d, i) => (
          <button
            key={i}
            onClick={() => onDayChange(i)}
            className={`px-3 py-1.5 rounded text-xs font-mono ${
              activeDay === i
                ? "bg-pitch-border text-turf border border-turf"
                : "text-muted border border-transparent hover:border-pitch-borderlight"
            }`}
          >
            {dateLabel(d)}
          </button>
        ))}
      </div>

      <div className="bg-pitch-surface border border-pitch-border rounded-lg p-6">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <p className="text-sm text-muted">{venue.name} — tap a slot to block / unblock</p>
          <div className="flex gap-4 text-xs">
            <Legend color="bg-pitch-surface border border-pitch-borderlight" label="Open" />
            <Legend color="bg-turf" label="Booked" />
            <Legend color="bg-danger/30 border border-danger/50" label="Blocked" />
          </div>
        </div>
        <div className="grid grid-cols-7 gap-2">
          {HOURS.map((h) => {
            const key = `${activeVenue}_${day.toDateString()}_${h}`;
            const st = slots[key];
            return (
              <button
                key={h}
                onClick={() => onToggleSlot(h)}
                className={`rounded-md py-3 text-xs font-mono text-center transition-colors ${STATUS_STYLE[st]}`}
              >
                {h % 12 === 0 ? 12 : h % 12}:00 {h < 12 ? "AM" : "PM"}
              </button>
            );
          })}
        </div>
      </div>
    </>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5 text-muted">
      <span className={`w-3 h-3 rounded-sm ${color}`} />
      {label}
    </div>
  );
}
