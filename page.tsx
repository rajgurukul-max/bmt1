"use client";

import { useMemo, useState } from "react";
import { IndianRupee, Receipt, TrendingUp } from "lucide-react";
import Sidebar, { Tab } from "@/components/Sidebar";
import Header from "@/components/Header";
import StatCard from "@/components/StatCard";
import BookingList from "@/components/BookingList";
import SlotCalendar from "@/components/SlotCalendar";
import PayoutsPanel from "@/components/PayoutsPanel";
import { VENUES, HOURS, BOOKINGS, getNextDays, seedSlots, SlotStatus } from "@/lib/data";

const DAYS = getNextDays(5);

export default function Page() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [activeVenue, setActiveVenue] = useState(VENUES[0].id);
  const [activeDay, setActiveDay] = useState(0);
  const [slots, setSlots] = useState<Record<string, SlotStatus>>(() =>
    seedSlots(VENUES, DAYS, HOURS)
  );

  const day = DAYS[activeDay];

  const toggleSlot = (h: number) => {
    const key = `${activeVenue}_${day.toDateString()}_${h}`;
    setSlots((prev) => {
      const cur = prev[key];
      if (cur === "booked") return prev; // real bookings aren't cleared from here
      return { ...prev, [key]: cur === "open" ? "blocked" : "open" };
    });
  };

  const stats = useMemo(() => {
    let bookedCount = 0;
    let total = 0;
    Object.values(slots).forEach((s) => {
      total++;
      if (s === "booked") bookedCount++;
    });
    return {
      occupancy: total ? Math.round((bookedCount / total) * 100) : 0,
      todayRevenue: BOOKINGS.filter((b) => b.date === "Today" && b.status === "confirmed").reduce(
        (a, b) => a + b.amount,
        0
      ),
      todayBookings: BOOKINGS.filter((b) => b.date === "Today").length,
    };
  }, [slots]);

  return (
    <div className="min-h-screen w-full bg-pitch text-chalk flex">
      <Sidebar activeTab={tab} onChange={setTab} />

      <main className="flex-1 overflow-auto">
        <Header tab={tab} />

        <div className="p-8">
          {tab === "dashboard" && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
                <StatCard
                  icon={IndianRupee}
                  label="Today's revenue"
                  value={`₹${stats.todayRevenue.toLocaleString("en-IN")}`}
                />
                <StatCard icon={Receipt} label="Bookings today" value={stats.todayBookings} />
                <StatCard icon={TrendingUp} label="5-day occupancy" value={`${stats.occupancy}%`} />
              </div>
              <div className="bg-pitch-surface border border-pitch-border rounded-lg p-6">
                <h2 className="text-sm font-medium text-muted mb-4 uppercase tracking-wide">
                  Recent bookings
                </h2>
                <BookingList bookings={BOOKINGS.slice(0, 3)} />
              </div>
            </>
          )}

          {tab === "calendar" && (
            <SlotCalendar
              activeVenue={activeVenue}
              onVenueChange={setActiveVenue}
              days={DAYS}
              activeDay={activeDay}
              onDayChange={setActiveDay}
              slots={slots}
              onToggleSlot={toggleSlot}
            />
          )}

          {tab === "bookings" && (
            <div className="bg-pitch-surface border border-pitch-border rounded-lg p-6">
              <BookingList bookings={BOOKINGS} />
            </div>
          )}

          {tab === "payouts" && <PayoutsPanel />}
        </div>
      </main>
    </div>
  );
}
