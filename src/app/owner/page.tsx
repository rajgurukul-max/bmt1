"use client";

import { useEffect, useState } from "react";
import { IndianRupee, Receipt, TrendingUp } from "lucide-react";
import Sidebar, { Tab } from "@/components/Sidebar";
import Header from "@/components/Header";
import StatCard from "@/components/StatCard";
import BookingList from "@/components/BookingList";
import SlotCalendar from "@/components/SlotCalendar";
import PayoutsPanel from "@/components/PayoutsPanel";
import AddVenueModal from "@/components/AddVenueModal";
import { HOURS, getNextDays, SlotStatus } from "@/lib/data";
import { getSupabaseAuth } from "@/lib/auth";

const DAYS = getNextDays(5);

export default function Page() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [activeVenue, setActiveVenue] = useState("");
  const [activeDay, setActiveDay] = useState(0);
  const [slots, setSlots] = useState<Record<string, SlotStatus>>({});
  const [venues, setVenues] = useState<any[]>([]);
  const [bookings, setBookings] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddVenue, setShowAddVenue] = useState(false);

  // Auth check
  useEffect(() => {
    const checkAuth = async () => {
      const supabase = getSupabaseAuth();
      const { data } = await supabase.auth.getSession();
      if (!data.session) {
        window.location.href = "/owner/login";
      }
    };
    checkAuth();
  }, []);

  // Fetch venues
useEffect(() => {
  const fetchVenues = async () => {
    const supabase = getSupabaseAuth();
    const { data: sessionData } = await supabase.auth.getSession();
    const token = sessionData?.session?.access_token;

    const res = await fetch("/api/venues", {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    const data = await res.json();
    if (Array.isArray(data) && data.length > 0) {
      setVenues(data);
      setActiveVenue(data[0].id);
    }
    setLoading(false);
  };
  fetchVenues().catch(() => setLoading(false));
}, []);


  // Fetch bookings
  useEffect(() => {
    fetch("/api/bookings")
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) setBookings(data);
      });
  }, []);

  // Fetch slots when venue or day changes
  useEffect(() => {
    if (!activeVenue) return;
    const date = DAYS[activeDay].toISOString().split("T")[0];
    fetch(`/api/slots?venue_id=${activeVenue}&date=${date}`)
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) {
          const newSlots: Record<string, SlotStatus> = {};
          HOURS.forEach((h) => {
            const key = `${activeVenue}_${DAYS[activeDay].toDateString()}_${h}`;
            const found = data.find((s: any) => s.hour === h);
            newSlots[key] = found ? found.status : "open";
          });
          setSlots((prev) => ({ ...prev, ...newSlots }));
        }
      });
  }, [activeVenue, activeDay]);

  const toggleSlot = async (h: number) => {
    const key = `${activeVenue}_${DAYS[activeDay].toDateString()}_${h}`;
    const current = slots[key];
    if (current === "booked") return;
    const newStatus = current === "open" ? "blocked" : "open";
    setSlots((prev) => ({ ...prev, [key]: newStatus }));
    const date = DAYS[activeDay].toISOString().split("T")[0];
    await fetch("/api/slots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ venue_id: activeVenue, date, hour: h, status: newStatus }),
    });
  };

  const handleVenueSaved = (newVenue: any) => {
    setVenues((prev) => [...prev, newVenue]);
    setActiveVenue(newVenue.id);
  };

  const stats = {
    todayRevenue: bookings
      .filter((b) => b.status === "confirmed")
      .reduce((a: number, b: any) => a + (b.amount || 0), 0),
    todayBookings: bookings.length,
    occupancy: Object.values(slots).length
      ? Math.round(
          (Object.values(slots).filter((s) => s === "booked").length /
            Object.values(slots).length) *
            100
        )
      : 0,
  };

  if (loading) {
    return (
      <div className="min-h-screen w-full bg-[#0E1F14] text-[#F4F7ED] flex items-center justify-center">
        <p className="text-[#8BC34A] font-mono animate-pulse">
          Loading BookMyTurfs...
        </p>
      </div>
    );
  }

  return (
    <div className="min-h-screen w-full bg-[#0E1F14] text-[#F4F7ED] flex font-sans">
      <Sidebar activeTab={tab} onChange={setTab} venues={venues} />
      <main className="flex-1 overflow-auto">
        <Header tab={tab} onAddVenue={() => setShowAddVenue(true)} />
        <div className="p-8">
          {tab === "dashboard" && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
                <StatCard
                  icon={IndianRupee}
                  label="Total revenue"
                  value={`₹${stats.todayRevenue.toLocaleString("en-IN")}`}
                />
                <StatCard
                  icon={Receipt}
                  label="Total bookings"
                  value={stats.todayBookings}
                />
                <StatCard
                  icon={TrendingUp}
                  label="Slot occupancy"
                  value={`${stats.occupancy}%`}
                />
              </div>
              <div className="bg-[#16291C] border border-[#1E3324] rounded-lg p-6">
                <h2 className="text-sm font-medium text-[#9FB0A3] mb-4 uppercase tracking-wide">
                  Recent bookings
                </h2>
                {bookings.length === 0 ? (
                  <p className="text-[#5C7066] text-sm">
                    No bookings yet — they'll appear here once users start booking.
                  </p>
                ) : (
                  <BookingList bookings={bookings.slice(0, 3)} />
                )}
              </div>
            </>
          )}
          {tab === "calendar" && venues.length > 0 && (
            <SlotCalendar
              activeVenue={activeVenue}
              onVenueChange={setActiveVenue}
              days={DAYS}
              activeDay={activeDay}
              onDayChange={setActiveDay}
              slots={slots}
              onToggleSlot={toggleSlot}
              venues={venues}
            />
          )}
          {tab === "calendar" && venues.length === 0 && (
            <div className="bg-[#16291C] border border-[#1E3324] rounded-lg p-8 text-center">
              <p className="text-[#9FB0A3] mb-4">No venues yet</p>
              <button
                onClick={() => setShowAddVenue(true)}
                className="bg-[#8BC34A] text-[#0E1F14] px-4 py-2 rounded-md text-sm font-medium"
              >
                Add your first venue
              </button>
            </div>
          )}
          {tab === "bookings" && (
            <div className="bg-[#16291C] border border-[#1E3324] rounded-lg p-6">
              {bookings.length === 0 ? (
                <p className="text-[#5C7066] text-sm">No bookings yet.</p>
              ) : (
                <BookingList bookings={bookings} />
              )}
            </div>
          )}
          {tab === "payouts" && <PayoutsPanel />}
        </div>
      </main>
      {showAddVenue && (
        <AddVenueModal
          onClose={() => setShowAddVenue(false)}
          onSave={handleVenueSaved}
        />
      )}
    </div>
  );
}

