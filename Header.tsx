"use client";

import { Plus } from "lucide-react";
import { Tab } from "./Sidebar";

const TITLES: Record<Tab, string> = {
  dashboard: "Today at a glance",
  calendar: "Slot Calendar",
  bookings: "Bookings",
  payouts: "Payouts",
};

export default function Header({ tab }: { tab: Tab }) {
  const today = new Date();
  return (
    <header className="px-8 py-6 border-b border-pitch-border flex items-center justify-between">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{TITLES[tab]}</h1>
        <p className="text-sm text-muted mt-1">
          {today.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
        </p>
      </div>
      <button className="flex items-center gap-2 bg-turf text-pitch text-sm font-medium px-4 py-2 rounded-md hover:bg-turf-light transition-colors">
        <Plus size={16} /> Add venue
      </button>
    </header>
  );
}
