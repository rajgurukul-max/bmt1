"use client";

import { useEffect, useState } from "react";
import { MapPin, IndianRupee, ArrowLeft } from "lucide-react";

const HOURS = Array.from({ length: 14 }, (_, i) => 6 + i);

declare global {
  interface Window {
    Razorpay: any;
  }
}

function formatHour(h: number) {
  return `${h % 12 === 0 ? 12 : h % 12}:00 ${h < 12 ? "AM" : "PM"}`;
}

export default function VenuePage({ params }: { params: { id: string } }) {
  const [venue, setVenue] = useState<any>(null);
  const [slots, setSlots] = useState<any[]>([]);
  const [selectedDate, setSelectedDate] = useState(
    new Date().toISOString().split("T")[0]
  );
  const [selectedSlots, setSelectedSlots] = useState<number[]>([]);
  const [booking, setBooking] = useState({ name: "", phone: "", players: "" });
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState(false);
  const [booked, setBooked] = useState(false);

  const DAYS = Array.from({ length: 5 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() + i);
    return d;
  });

  useEffect(() => {
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    document.body.appendChild(script);

    fetch(`/api/public/venues/${params.id}`)
      .then((r) => r.json())
      .then((data) => {
        setVenue(data);
        setLoading(false);
      });
  }, [params.id]);

  useEffect(() => {
    fetch(`/api/public/slots?venue_id=${params.id}&date=${selectedDate}`)
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) setSlots(data);
      });
  }, [params.id, selectedDate]);

  const getSlotStatus = (hour: number) => {
    const slot = slots.find((s) => s.hour === hour);
    return slot ? slot.status : "open";
  };

  const toggleSlot = (h: number) => {
    setSelectedSlots((prev) =>
      prev.includes(h) ? prev.filter((x) => x !== h) : [...prev, h].sort((a, b) => a - b)
    );
  };

  const totalAmount = selectedSlots.length * Number(venue?.price_per_hour || 0);

  const handlePayment = async () => {
    if (selectedSlots.length === 0 || !booking.name || !booking.phone) return;
    setPaying(true);

    try {
      // Step 1 — Create a booking row per selected hour, tagged with a shared group id
      const bookingGroupId = crypto.randomUUID();

      const bookingResults = await Promise.all(
        selectedSlots.map((hour) =>
          fetch("/api/public/bookings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              venue_id: params.id,
              hour,
              date: selectedDate,
              player_name: String(booking.name),
              player_phone: String(booking.phone),
              players: Number(booking.players) || 1,
              amount: Number(venue?.price_per_hour),
              status: "pending",
              payment_id: "",
              booking_date: selectedDate,
              booking_group_id: bookingGroupId,
            }),
          }).then((r) => r.json())
        )
      );

      const bookingIds = bookingResults.map((b) => b?.[0]?.id).filter(Boolean);

      // Step 2 — Create one Razorpay order for the combined total
      const orderRes = await fetch("/api/payment/create-order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          amount: totalAmount,
          venue_name: venue?.name,
          booking_id: bookingGroupId,
        }),
      });
      const order = await orderRes.json();

      // Step 3 — Open Razorpay
      const slotSummary = selectedSlots.map(formatHour).join(", ");
      const options = {
        key: process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID,
        amount: order.amount,
        currency: "INR",
        name: "BookMyTurfs",
        description: `${venue?.name} - ${slotSummary}`,
        order_id: order.id,
        prefill: {
          name: booking.name,
          contact: booking.phone,
        },
        theme: { color: "#8BC34A" },
        handler: async (response: any) => {
          await Promise.all(
            bookingIds.map((bookingId) =>
              fetch(`/api/payment/confirm`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  booking_id: bookingId,
                  payment_id: response.razorpay_payment_id,
                }),
              })
            )
          );
          setBooked(true);
        },
        modal: {
          ondismiss: () => setPaying(false),
        },
      };

      const rzp = new window.Razorpay(options);
      rzp.open();
    } catch (e) {
      alert("Something went wrong. Please try again.");
      setPaying(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0E1F14] flex items-center justify-center">
        <p className="text-[#8BC34A] font-mono animate-pulse">Loading...</p>
      </div>
    );
  }

  if (booked) {
    return (
      <div className="min-h-screen bg-[#0E1F14] flex items-center justify-center px-6">
        <div className="text-center">
          <div className="text-5xl mb-4">🎉</div>
          <h1 className="text-2xl font-bold text-[#F4F7ED] mb-2">
            Booking Confirmed!
          </h1>
          <p className="text-[#9FB0A3] mb-2">{venue?.name}</p>
          <p className="text-[#8BC34A] font-mono mb-2">
            {selectedDate} · {selectedSlots.map(formatHour).join(", ")}
          </p>
          <p className="text-[#9FB0A3] text-sm mb-6">
            Payment successful! See you at the turf. 🏏
          </p>
          <a
            href="/book"
            className="bg-[#8BC34A] text-[#0E1F14] px-6 py-3 rounded-lg font-medium"
          >
            Book another turf
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0E1F14] text-[#F4F7ED]">
      <div className="border-b border-[#1E3324] px-6 py-4 flex items-center gap-3">
        <a href="/book" className="text-[#9FB0A3] hover:text-[#F4F7ED]">
          <ArrowLeft size={20} />
        </a>
        <div className="font-mono text-[#8BC34A] text-sm tracking-[0.2em] uppercase">
          BookMyTurfs
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold mb-1">{venue?.name}</h1>
          <div className="flex items-center gap-4 text-sm text-[#9FB0A3]">
            <span className="flex items-center gap-1">
              <MapPin size={13} /> {venue?.area}
            </span>
            <span className="flex items-center gap-1">
              <IndianRupee size={13} />
              {venue?.price_per_hour?.toLocaleString("en-IN")}/hr
            </span>
          </div>
          <p className="text-[#9FB0A3] text-sm mt-2">{venue?.description}</p>
        </div>

        {/* Date selector */}
        <div className="mb-6">
          <h2 className="text-sm font-medium text-[#9FB0A3] uppercase tracking-wide mb-3">
            Select Date
          </h2>
          <div className="flex gap-2 flex-wrap">
            {DAYS.map((d) => {
              const dateStr = d.toISOString().split("T")[0];
              return (
                <button
                  key={dateStr}
                  onClick={() => {
                    setSelectedDate(dateStr);
                    setSelectedSlots([]);
                  }}
                  className={`px-3 py-2 rounded-lg text-xs font-mono border transition-colors ${
                    selectedDate === dateStr
                      ? "bg-[#8BC34A] text-[#0E1F14] border-[#8BC34A]"
                      : "border-[#2C4A33] text-[#9FB0A3] hover:border-[#8BC34A]"
                  }`}
                >
                  {d.toLocaleDateString("en-IN", {
                    weekday: "short",
                    day: "numeric",
                    month: "short",
                  })}
                </button>
              );
            })}
          </div>
        </div>

        {/* Slot selector */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-[#9FB0A3] uppercase tracking-wide">
              Select Time Slot(s)
            </h2>
            {selectedSlots.length > 0 && (
              <span className="text-xs text-[#8BC34A]">
                {selectedSlots.length} selected
              </span>
            )}
          </div>
          <p className="text-xs text-[#5C7066] mb-3">
            Tap multiple hours to book them together — even non-consecutive ones.
          </p>
          <div className="grid grid-cols-4 gap-2">
            {HOURS.map((h) => {
              const status = getSlotStatus(h);
              const isSelected = selectedSlots.includes(h);
              return (
                <button
                  key={h}
                  disabled={status === "blocked" || status === "booked"}
                  onClick={() => toggleSlot(h)}
                  className={`py-2.5 rounded-lg text-xs font-mono border transition-colors ${
                    status === "blocked" || status === "booked"
                      ? "bg-[#E5484D]/20 border-[#E5484D]/30 text-[#E5484D]/50 cursor-not-allowed"
                      : isSelected
                      ? "bg-[#8BC34A] border-[#8BC34A] text-[#0E1F14] font-semibold"
                      : "bg-[#16291C] border-[#2C4A33] text-[#8BC34A] hover:border-[#8BC34A]"
                  }`}
                >
                  {formatHour(h)}
                </button>
              );
            })}
          </div>
        </div>

        {/* Booking form */}
        {selectedSlots.length > 0 && (
          <div className="bg-[#16291C] border border-[#1E3324] rounded-xl p-5">
            <h2 className="font-medium mb-1">
              Booking {selectedSlots.length} slot{selectedSlots.length > 1 ? "s" : ""}
            </h2>
            <p className="text-xs text-[#9FB0A3] mb-4">
              {selectedSlots.map(formatHour).join(" · ")}
            </p>
            <div className="space-y-3 mb-4">
              <input
                value={booking.name}
                onChange={(e) =>
                  setBooking({ ...booking, name: e.target.value })
                }
                placeholder="Your name *"
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-sm text-[#F4F7ED] placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
              />
              <input
                value={booking.phone}
                onChange={(e) =>
                  setBooking({ ...booking, phone: e.target.value })
                }
                placeholder="Phone number *"
                type="tel"
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-sm text-[#F4F7ED] placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
              />
              <input
                value={booking.players}
                onChange={(e) =>
                  setBooking({ ...booking, players: e.target.value })
                }
                placeholder="Number of players"
                type="number"
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-sm text-[#F4F7ED] placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
              />
            </div>
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm text-[#9FB0A3]">
                Total amount ({selectedSlots.length} × ₹{venue?.price_per_hour?.toLocaleString("en-IN")})
              </span>
              <span className="font-mono font-semibold text-[#8BC34A]">
                ₹{totalAmount.toLocaleString("en-IN")}
              </span>
            </div>
            <button
              onClick={handlePayment}
              disabled={paying || !booking.name || !booking.phone}
              className="w-full bg-[#8BC34A] text-[#0E1F14] font-medium py-3 rounded-lg hover:bg-[#9BCF5E] transition-colors disabled:opacity-50"
            >
              {paying ? "Processing..." : `Pay ₹${totalAmount.toLocaleString("en-IN")}`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
