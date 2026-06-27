"use client";

import { useEffect, useState } from "react";
import { MapPin, IndianRupee, ArrowLeft } from "lucide-react";

const HOURS = Array.from({ length: 14 }, (_, i) => 6 + i);

declare global {
  interface Window {
    Razorpay: any;
  }
}

export default function VenuePage({ params }: { params: { id: string } }) {
  const [venue, setVenue] = useState<any>(null);
  const [slots, setSlots] = useState<any[]>([]);
  const [selectedDate, setSelectedDate] = useState(
    new Date().toISOString().split("T")[0]
  );
  const [selectedSlot, setSelectedSlot] = useState<number | null>(null);
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
    // Load Razorpay script
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

  const handlePayment = async () => {
  if (!selectedSlot || !booking.name || !booking.phone) return;
  setPaying(true);

  try {
    // Step 1 — Create booking first with pending status
    const bookingRes = await fetch("/api/public/bookings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        venue_id: params.id,
        hour: selectedSlot,
        date: selectedDate,
        player_name: booking.name,
        player_phone: booking.phone,
        players: parseInt(booking.players) || 1,
        amount: venue?.price_per_hour,
        status: "pending",
        payment_id: "",
        booking_date: selectedDate,
      }),
    });
    const bookingData = await bookingRes.json();
    const bookingId = bookingData?.[0]?.id;

    // Step 2 — Create Razorpay order
    const orderRes = await fetch("/api/payment/create-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        amount: venue?.price_per_hour,
        venue_name: venue?.name,
        booking_id: bookingId,
      }),
    });
    const order = await orderRes.json();

    // Step 3 — Open Razorpay
    const options = {
      key: process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID,
      amount: order.amount,
      currency: "INR",
      name: "BookMyTurfs",
      description: `${venue?.name} - ${selectedSlot}:00 ${selectedSlot < 12 ? "AM" : "PM"}`,
      order_id: order.id,
      prefill: {
        name: booking.name,
        contact: booking.phone,
      },
      theme: { color: "#8BC34A" },
      handler: async (response: any) => {
        // Card payment success
        await fetch(`/api/payment/confirm`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            booking_id: bookingId,
            payment_id: response.razorpay_payment_id,
          }),
        });
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
            {selectedDate} at {selectedSlot}:00{" "}
            {selectedSlot! < 12 ? "AM" : "PM"}
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
                    setSelectedSlot(null);
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
          <h2 className="text-sm font-medium text-[#9FB0A3] uppercase tracking-wide mb-3">
            Select Time Slot
          </h2>
          <div className="grid grid-cols-4 gap-2">
            {HOURS.map((h) => {
              const status = getSlotStatus(h);
              const isSelected = selectedSlot === h;
              return (
                <button
                  key={h}
                  disabled={status === "blocked" || status === "booked"}
                  onClick={() => setSelectedSlot(h)}
                  className={`py-2.5 rounded-lg text-xs font-mono border transition-colors ${
                    status === "blocked" || status === "booked"
                      ? "bg-[#E5484D]/20 border-[#E5484D]/30 text-[#E5484D]/50 cursor-not-allowed"
                      : isSelected
                      ? "bg-[#8BC34A] border-[#8BC34A] text-[#0E1F14] font-semibold"
                      : "bg-[#16291C] border-[#2C4A33] text-[#8BC34A] hover:border-[#8BC34A]"
                  }`}
                >
                  {h % 12 === 0 ? 12 : h % 12}:00{" "}
                  {h < 12 ? "AM" : "PM"}
                </button>
              );
            })}
          </div>
        </div>

        {/* Booking form */}
        {selectedSlot && (
          <div className="bg-[#16291C] border border-[#1E3324] rounded-xl p-5">
            <h2 className="font-medium mb-4">
              Booking for {selectedSlot % 12 === 0 ? 12 : selectedSlot % 12}
              :00 {selectedSlot < 12 ? "AM" : "PM"}
            </h2>
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
              <span className="text-sm text-[#9FB0A3]">Total amount</span>
              <span className="font-mono font-semibold text-[#8BC34A]">
                ₹{venue?.price_per_hour?.toLocaleString("en-IN")}
              </span>
            </div>
            <button
              onClick={handlePayment}
              disabled={paying || !booking.name || !booking.phone}
              className="w-full bg-[#8BC34A] text-[#0E1F14] font-medium py-3 rounded-lg hover:bg-[#9BCF5E] transition-colors disabled:opacity-50"
            >
              {paying ? "Processing..." : `Pay ₹${venue?.price_per_hour?.toLocaleString("en-IN")}`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
