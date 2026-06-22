"use client";

import { LayoutGrid, CalendarDays, Receipt, Wallet } from "lucide-react";
import { VENUES } from "@/lib/data";

export type Tab = "dashboard" | "calendar" | "bookings" | "payouts";

const NAV_ITEMS: { id: Tab; label: string; icon: typeof LayoutGrid }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutGrid },
  { id: "calendar", label: "Slot Calendar", icon: CalendarDays },
  { id: "bookings", label: "Bookings", icon: Receipt },
  { id: "payouts", label: "Payouts", icon: Wallet },
];

export default function Sidebar({
  activeTab,
  onChange,
}: {
  activeTab: Tab;
  onChange: (tab: Tab) => void;
}) {
  return (
    <aside className="w-60 shrink-0 border-r border-pitch-border flex flex-col">
      <div className="px-6 py-6 border-b border-pitch-border">
        <div className="font-mono text-turf text-xs tracking-[0.2em] uppercase">BookMyTurfs</div>
        <div className="text-sm text-muted mt-1">Owner Console</div>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => onChange(id)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors ${
              activeTab === id
                ? "bg-pitch-border text-turf"
                : "text-muted hover:bg-pitch-surface hover:text-chalk"
            }`}
          >
            <Icon size={16} strokeWidth={2} />
            {label}
          </button>
        ))}
      </nav>
      <div className="px-6 py-4 border-t border-pitch-border text-xs text-dim">
        {VENUES.length} venues live · Mumbai
      </div>
    </aside>
  );
}
