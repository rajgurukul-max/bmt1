"use client";
import { LayoutGrid, CalendarDays, Receipt, Wallet } from "lucide-react";

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
  venues = [],
}: {
  activeTab: Tab;
  onChange: (tab: Tab) => void;
  venues: any[];
}) {
  return (
    <aside className="w-60 shrink-0 border-r border-[#1E3324] flex flex-col">
      <div className="px-6 py-6 border-b border-[#1E3324]">
        <div className="font-mono text-[#8BC34A] text-xs tracking-[0.2em] uppercase">BookMyTurfs</div>
        <div className="text-sm text-[#9FB0A3] mt-1">Owner Console</div>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => onChange(id)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors ${
              activeTab === id ? "bg-[#1E3324] text-[#8BC34A]" : "text-[#9FB0A3] hover:bg-[#16291C] hover:text-[#F4F7ED]"
            }`}>
            <Icon size={16} strokeWidth={2} />{label}
          </button>
        ))}
      </nav>
      <div className="px-6 py-4 border-t border-[#1E3324] text-xs text-[#5C7066]">
        {venues.length} venues live · Mumbai
      </div>
    </aside>
  );
}
