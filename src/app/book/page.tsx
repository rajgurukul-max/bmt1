"use client";

import { useEffect, useState } from "react";
import { MapPin, IndianRupee, Search, Shield, Zap, Star } from "lucide-react";

const SPORTS = [
  { name: "All", icon: "🏆" },
  { name: "Cricket", icon: "🏏" },
  { name: "Football", icon: "⚽" },
  { name: "Badminton", icon: "🏸" },
  { name: "Tennis", icon: "🎾" },
  { name: "Basketball", icon: "🏀" },
];

const STATS = [
  { icon: Shield, label: "Secure Payments", value: "100%" },
  { icon: Zap, label: "Instant Confirmation", value: "< 1 min" },
  { icon: Star, label: "Happy Players", value: "500+" },
];

export default function BookPage() {
  const [venues, setVenues] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sport, setSport] = useState("All");

  useEffect(() => {
    fetch("/api/public/venues")
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) setVenues(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const filtered = venues.filter((v) => {
    const matchSport = sport === "All" || v.sport === sport;
    const matchSearch =
      v.name.toLowerCase().includes(search.toLowerCase()) ||
      v.area.toLowerCase().includes(search.toLowerCase());
    return matchSport && matchSearch;
  });

  return (
    <div className="min-h-screen bg-[#0E1F14] text-[#F4F7ED]">
      {/* Navbar */}
      <nav className="border-b border-[#1E3324] px-6 py-4 flex items-center justify-between">
        <div className="font-mono text-[#8BC34A] text-sm tracking-[0.2em] uppercase font-bold">
          BookMyTurfs
        </div>
        <a
          href="/owner/login"
          className="text-xs text-[#9FB0A3] hover:text-[#8BC34A] transition-colors border border-[#2C4A33] px-3 py-1.5 rounded-md hover:border-[#8BC34A]"
        >
          Owner login →
        </a>
      </nav>

      {/* Hero Banner */}
      <div className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-[#1A3D20] to-[#0E1F14] opacity-80" />
        <div className="relative px-6 py-16 text-center max-w-3xl mx-auto">
          <div className="inline-block bg-[#8BC34A]/20 border border-[#8BC34A]/30 text-[#8BC34A] text-xs px-3 py-1 rounded-full mb-4 font-mono">
            🏟️ Mumbai's #1 Turf Booking Platform
          </div>
          <h1 className="text-4xl font-bold mb-4 leading-tight">
            Book Mumbai's Best
            <span className="text-[#8BC34A]"> Turfs </span>
            Instantly
          </h1>
          <p className="text-[#9FB0A3] text-lg mb-8">
            Cricket · Football · Badminton — Pay online, play today
          </p>

          {/* Search bar */}
          <div className="relative max-w-lg mx-auto">
            <Search
              size={18}
              className="absolute left-4 top-1/2 -translate-y-1/2 text-[#5C7066]"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by turf name or area..."
              className="w-full bg-[#16291C] border border-[#2C4A33] rounded-xl pl-11 pr-4 py-4 text-sm text-[#F4F7ED] placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A] shadow-lg"
            />
          </div>

          {/* Stats */}
          <div className="flex items-center justify-center gap-8 mt-10">
            {STATS.map(({ icon: Icon, label, value }) => (
              <div key={label} className="text-center">
                <div className="flex items-center justify-center gap-1.5 text-[#8BC34A] mb-1">
                  <Icon size={14} />
                  <span className="font-mono font-bold text-sm">{value}</span>
                </div>
                <p className="text-[#9FB0A3] text-xs">{label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Sport Category Cards */}
      <div className="px-6 py-8 max-w-4xl mx-auto">
        <h2 className="text-sm font-medium text-[#9FB0A3] uppercase tracking-wide mb-4">
          Browse by Sport
        </h2>
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-10">
          {SPORTS.map((s) => (
            <button
              key={s.name}
              onClick={() => setSport(s.name)}
              className={`flex flex-col items-center gap-2 py-4 px-2 rounded-xl border transition-all ${
                sport === s.name
                  ? "bg-[#8BC34A] border-[#8BC34A] text-[#0E1F14]"
                  : "bg-[#16291C] border-[#1E3324] text-[#9FB0A3] hover:border-[#8BC34A] hover:text-[#F4F7ED]"
              }`}
            >
              <span className="text-2xl">{s.icon}</span>
              <span className="text-xs font-medium">{s.name}</span>
            </button>
          ))}
        </div>

        {/* Venues count */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium text-[#9FB0A3] uppercase tracking-wide">
            {sport === "All" ? "All Venues" : `${sport} Venues`}
            <span className="ml-2 text-[#8BC34A]">({filtered.length})</span>
          </h2>
          {sport !== "All" && (
            <button
              onClick={() => setSport("All")}
              className="text-xs text-[#9FB0A3] hover:text-[#F4F7ED]"
            >
              Clear filter ×
            </button>
          )}
        </div>

        {/* Venues grid */}
        {loading ? (
          <div className="text-center py-16">
            <p className="text-[#8BC34A] font-mono animate-pulse">
              Loading turfs...
            </p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-16">
            <p className="text-4xl mb-4">🏟️</p>
            <p className="text-[#9FB0A3]">No turfs found — try a different search.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {filtered.map((v) => (
              <a
                key={v.id}
                href={`/book/${v.id}`}
                className="bg-[#16291C] border border-[#1E3324] rounded-xl p-5 hover:border-[#8BC34A] transition-all hover:shadow-lg hover:shadow-[#8BC34A]/10 group"
              >
                {/* Sport badge */}
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <h2 className="font-semibold text-[#F4F7ED] group-hover:text-[#8BC34A] transition-colors">
                      {v.name}
                    </h2>
                    <div className="flex items-center gap-1 text-[#9FB0A3] text-xs mt-1">
                      <MapPin size={11} />
                      {v.area}, Mumbai
                    </div>
                  </div>
                  <span className="text-lg">
                    {SPORTS.find((s) => s.name === v.sport)?.icon || "🏆"}
                  </span>
                </div>

                <p className="text-xs text-[#9FB0A3] mb-4 line-clamp-2">
                  {v.description}
                </p>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1 font-mono text-sm text-[#F4F7ED]">
                    <IndianRupee size={13} />
                    <span className="font-semibold">
                      {v.price_per_hour?.toLocaleString("en-IN")}
                    </span>
                    <span className="text-[#9FB0A3] text-xs">/hr</span>
                  </div>
                  <span className="text-xs bg-[#8BC34A]/20 text-[#8BC34A] px-2 py-1 rounded-full border border-[#8BC34A]/30 group-hover:bg-[#8BC34A] group-hover:text-[#0E1F14] transition-colors">
                    Book now →
                  </span>
                </div>
              </a>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-[#1E3324] px-6 py-8 text-center mt-8">
        <div className="font-mono text-[#8BC34A] text-xs tracking-[0.2em] uppercase mb-2">
          BookMyTurfs
        </div>
        <p className="text-[#5C7066] text-xs">
          Mumbai's premier turf booking platform · bookmyturfs.com
        </p>
        <p className="text-[#5C7066] text-xs mt-1">
          Are you a turf owner?{" "}
          <a href="/owner/login" className="text-[#8BC34A] hover:underline">
            List your venue →
          </a>
        </p>
      </div>
    </div>
  );
}
