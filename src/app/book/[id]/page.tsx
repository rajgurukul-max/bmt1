"use client";

import { useEffect, useState, useMemo } from "react";
import { MapPin, IndianRupee, ArrowLeft, Tag, X } from "lucide-react";

const HOURS = Array.from({ length: 14 }, (_, i) => 6 + i);

// Easy to tweak later — no other code needs to change
const STRETCH_DISCOUNT = { minHours: 3, percentOff: 10 };

declare global {
  interface Window {
    Razorpay: any;
  }
}

function formatHour(h: number) {
  return `${h % 12 === 0 ? 12 : h % 12}:00 ${h < 12 ? "AM" : "PM"}`;
}

function getContiguousRuns(hours: number[]): number[][] {
  if (!hours.length) return [];
  const sorted = [...hours].sort((a, b) => a - b);
  const runs: number[][] = [];
  let current: number[] = [sorted[0]];
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] === sorted[i - 1] + 1) {
      current.push(sorted[i]);
    } else {
      runs.push(current);
      current = [sorted[i]];
    }
  }
  runs.push(current);
  return runs;
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
  const [activePhoto, setActivePhoto] = useState(0);

  const [promoInput, setPromoInput] = useState("");
  const [promoApplied, setPromoApplied] = useState<any>(null);
  const [promoError, setPromoError] = useState("");
  const [checkingPromo, setCheckingPromo] = useState(false);

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

  // Stretch discount — only contiguous runs meeting the minimum qualify
  const stretchDiscount = useMemo(() => {
    const runs = getContiguousRuns(selectedSlots);
    let discount = 0;
    for (const run of runs) {
      if (run.length >= STRETCH_DISCOUNT.minHours) {
        const runAmount = run.length * Number(venue?.price_per_hour || 0);
        discount += Math.round((runAmount * STRETCH_DISCOUNT.percentOff) / 100);
      }
    }
    return discount;
  }, [selectedSlots, venue]);

  const hasQualifyingStretch = getContiguousRuns(selectedSlots).some(
    (run) => run.length >= STRETCH_DISCOUNT.minHours
  );

  // Re-validate the applied promo whenever the total changes (e.g. slots added/removed)
  useEffect(() => {
    if (promoApplied && promoApplied.min_amount && totalAmount < promoApplied.min_amount) {
      setPromoApplied(null);
      setPromoError(`This code needs a minimum order of ₹${promoApplied.min_amount}`);
    }
  }, [totalAmount]);

  const applyPromo = async () => {
    if (!promoInput.trim()) return;
    setCheckingPromo(true);
    setPromoError("");
    try {
      const res = await fetch("/api/promos");
      const data = await res.json();
      const match = Array.isArray(data)
        ? data.find((p: any) => p.code === promoInput.trim().toUpperCase())
        : null;

      if (!match) {
        setPromoError("Invalid promo code");
      } else if (!match.is_active) {
        setPromoError("This promo code is no longer active");
      } else if (match.expires_at && new Date(match.expires_at) < new Date()) {
        setPromoError("This promo code has expired");
      } else if (match.max_uses && match.used_count >= match.max_uses) {
        setPromoError("This promo code has reached its usage limit");
      } else if (match.min_amount && totalAmount < match.min_amount) {
        setPromoError(`Minimum order amount is ₹${match.min_amount}`);
      } else {
        setPromoApplied(match);
        setPromoError("");
      }
    } catch (e) {
      setPromoError("Could not validate promo code right now");
    }
    setCheckingPromo(false);
  };

  const removePromo = () => {
    setPromoApplied(null);
    setPromoInput("");
    setPromoError("");
  };

  const promoDiscountAmount = promoApplied
    ? promoApplied.discount_type === "percent"
      ? Math.round((totalAmount * Number(promoApplied.discount_value)) / 100)
      : Math.min(Number(promoApplied.discount_value), totalAmount)
    : 0;

  // No stacking — whichever discount is bigger is the one that applies
  const usingStretch = stretchDiscount >= promoDiscountAmount;
  const discountAmount = Math.max(stretchDiscount, promoDiscountAmount);
  const discountSource = discountAmount === 0 ? null : usingStretch ? "stretch" : "promo";

  const finalAmount = totalAmount - discountAmount;

  const handlePayment = async () => {
    if (selectedSlots.length === 0 || !booking.name || !booking.phone) return;
    setPaying(true);

    try {
      const bookingGroupId = crypto.randomUUID();
      const perSlotDiscount = selectedSlots.length
        ? Math.round(discountAmount / selectedSlots.length)
        : 0;

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
              amount: Number(venue?.price_per_hour) - perSlotDiscount,
              status: "pending",
              payment_id: "",
              booking_date: selectedDate,
              booking_group_id: bookingGroupId,
              promo_code: discountSource === "promo" ? promoApplied?.code : null,
              discount_applied: perSlotDiscount,
              discount_type: discountSource,
            }),
          }).then((r) => r.json())
        )
      );

      const bookingIds = bookingResults.map((b) => b?.[0]?.id).filter(Boolean);

      const orderRes = await fetch("/api/payment/create-order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          amount: finalAmount,
          venue_name: venue?.name,
          booking_id: bookingGroupId,
        }),
      });
      const order = await orderRes.json();

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

          // Only count the promo code as "used" if it was actually the better discount
          if (discountSource === "promo" && promoApplied?.id) {
            fetch("/api/promos", {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ id: promoApplied.id, increment_use: true }),
            }).catch(() => {});
          }

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

  const photos: string[] = venue?.photos || [];

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

        {/* Photo gallery */}
        {photos.length > 0 && (
          <div className="mb-6">
            <div className="h-56 rounded-xl overflow-hidden bg-[#16291C]">
              <img
                src={photos[activePhoto]}
                alt={venue?.name}
                className="w-full h-full object-cover"
              />
            </div>
            {photos.length > 1 && (
              <div className="flex gap-2 mt-2">
                {photos.map((src, i) => (
                  <button
                    key={i}
                    onClick={() => setActivePhoto(i)}
                    className={`w-16 h-16 rounded-lg overflow-hidden border-2 transition-colors ${
                      activePhoto === i ? "border-[#8BC34A]" : "border-transparent opacity-70"
                    }`}
                  >
                    <img src={src} alt={`${venue?.name} ${i + 1}`} className="w-full h-full object-cover" />
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

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
            Book {STRETCH_DISCOUNT.minHours}+ hours in a row for an automatic{" "}
            {STRETCH_DISCOUNT.percentOff}% discount.
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
          {hasQualifyingStretch && (
            <p className="text-xs text-[#8BC34A] mt-2">
              🎉 You've got a {STRETCH_DISCOUNT.minHours}+ hour stretch — discount applied automatically below.
            </p>
          )}
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

            {/* Promo code */}
            <div className="mb-4">
              {!promoApplied ? (
                <>
                  <div className="flex gap-2">
                    <div className="relative flex-1">
                      <Tag
                        size={14}
                        className="absolute left-3 top-1/2 -translate-y-1/2 text-[#5C7066]"
                      />
                      <input
                        value={promoInput}
                        onChange={(e) => setPromoInput(e.target.value.toUpperCase())}
                        placeholder="Have a promo code?"
                        className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg pl-9 pr-3 py-2.5 text-sm text-[#F4F7ED] placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
                      />
                    </div>
                    <button
                      onClick={applyPromo}
                      disabled={checkingPromo || !promoInput.trim()}
                      className="px-4 py-2.5 rounded-lg text-sm font-medium border border-[#2C4A33] text-[#8BC34A] hover:border-[#8BC34A] transition-colors disabled:opacity-50"
                    >
                      {checkingPromo ? "..." : "Apply"}
                    </button>
                  </div>
                  {promoError && (
                    <p className="text-[#E5484D] text-xs mt-2">{promoError}</p>
                  )}
                </>
              ) : (
                <div className="flex items-center justify-between bg-[#8BC34A]/10 border border-[#8BC34A]/30 rounded-lg px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <Tag size={14} className="text-[#8BC34A]" />
                    <span className="text-sm text-[#8BC34A] font-mono font-semibold">
                      {promoApplied.code}
                    </span>
                    <span className="text-xs text-[#9FB0A3]">
                      {discountSource === "promo"
                        ? `applied — ₹${discountAmount.toLocaleString("en-IN")} off`
                        : "your stretch discount is already better, so this isn't needed"}
                    </span>
                  </div>
                  <button onClick={removePromo} className="text-[#9FB0A3] hover:text-[#F4F7ED]">
                    <X size={16} />
                  </button>
                </div>
              )}
            </div>

            {/* Price breakdown */}
            <div className="space-y-1.5 mb-4">
              <div className="flex items-center justify-between text-sm">
                <span className="text-[#9FB0A3]">
                  Subtotal ({selectedSlots.length} × ₹{venue?.price_per_hour?.toLocaleString("en-IN")})
                </span>
                <span className="font-mono text-[#F4F7ED]">
                  ₹{totalAmount.toLocaleString("en-IN")}
                </span>
              </div>
              {discountAmount > 0 && (
                <div className="flex items-center justify-between text-sm">
                  <span className="text-[#8BC34A]">
                    {discountSource === "stretch" ? "Stretch discount" : "Promo discount"}
                  </span>
                  <span className="font-mono text-[#8BC34A]">
                    −₹{discountAmount.toLocaleString("en-IN")}
                  </span>
                </div>
              )}
              <div className="flex items-center justify-between pt-1.5 border-t border-[#1E3324]">
                <span className="text-sm font-medium text-[#F4F7ED]">Total amount</span>
                <span className="font-mono font-semibold text-[#8BC34A]">
                  ₹{finalAmount.toLocaleString("en-IN")}
                </span>
              </div>
            </div>

            <button
              onClick={handlePayment}
              disabled={paying || !booking.name || !booking.phone}
              className="w-full bg-[#8BC34A] text-[#0E1F14] font-medium py-3 rounded-lg hover:bg-[#9BCF5E] transition-colors disabled:opacity-50"
            >
              {paying ? "Processing..." : `Pay ₹${finalAmount.toLocaleString("en-IN")}`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
