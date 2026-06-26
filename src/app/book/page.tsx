"use client";

import { useEffect, useState } from "react";
import { MapPin, Clock, IndianRupee, Search } from "lucide-react";

const SPORTS = ["All", "Cricket", "Football", "Badminton", "Tennis", "Basketball"];

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
      {/* Header */}
      <div className="border-b border-[#1E3324] px-6 py-4 flex items-center justify-between">
        <div className="font-mono text-[#8BC34A] text-sm tracking-[0.2em] uppercase">
          BookMyTurfs
        </div>
        <a
          href="/login"
          className="text-xs text-[#9FB0A3] hover:text-[#F4F7ED] transition-colors"
        >
          Owner login →
        </a>
      </div>

      {/* Hero */}
      <div className="px-6 py-12 text-center">
        <h1 className="text-3xl font-bold mb-2">Book a Turf in Mumbai</h1>
        <p className="text-[#9FB0A3] mb-8">
          Find and book the best sports turfs near you
        </p>

        {/* Search */}
        <div className="max-w-md mx-auto relative mb-6">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[#5C7066]"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or area..."
            className="w-full bg-[#16291C] border border-[#2C4A33] rounded-lg pl-9 pr-4 py-3 text-sm text-[#F4F7ED] placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
          />
        </div>

        {/* Sport filter */}
        <div className="flex gap-2 justify-center flex-wrap">
          {SPORTS.map((s) => (
            <button
              key={s}
              onClick={() => setSport(s)}
              className={`px-4 py-1.5 rounded-full text-xs border transition-colors ${
                sport === s
                  ? "bg-[#8BC34A] text-[#0E1F14] border-[#8BC34A] font-medium"
                  : "border-[#2C4A33] text-[#9FB0A3] hover:border-[#8BC34A]"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Venues grid */}
      <div className="px-6 pb-12 max-w-4xl mx-auto">
        {loading ? (
          <p className="text-center text-[#8BC34A] font-mono animate-pulse">
            Loading turfs...
          </p>
        ) : filtered.length === 0 ? (
          <p className="text-center text-[#9FB0A3]">
            No turfs found — try a different search.
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {filtered.map((v) => (
              <a
                key={v.id}
                href={`/book/${v.id}`}
                className="bg-[#16291C] border border-[#1E3324] rounded-xl p-5 hover:border-[#8BC34A] transition-colors group"
              >
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <h2 className="font-semibold group-hover:text-[#8BC34A] transition-colors">
                      {v.name}
                    </h2>
                    <div className="flex items-center gap-1 text-[#9FB0A3] text-xs mt-1">
                      <MapPin size={11} />
                      {v.area}
                    </div>
                  </div>
                  <span className="text-xs bg-[#0E1F14] border border-[#2C4A33] px-2 py-1 rounded-full text-[#8BC34A]">
                    {v.sport}
                  </span>
                </div>
                <p className="text-xs text-[#9FB0A3] mb-3 line-clamp-2">
                  {v.description}
                </p>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1 text-sm font-mono">
                    <IndianRupee size={13} />
                    {v.price_per_hour?.toLocaleString("en-IN")}/hr
                  </div>
                  <span className="text-xs text-[#8BC34A]">
                    View slots →
                  </span>
                </div>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
