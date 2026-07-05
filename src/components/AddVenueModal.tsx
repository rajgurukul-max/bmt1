"use client";
import { useState } from "react";
import { X } from "lucide-react";

const SPORTS = [
  "Football", "Cricket", "Box Cricket", "Badminton", "Tennis",
  "Swimming", "Pickleball", "Basketball", "Volleyball",
  "Table Tennis", "Squash", "Futsal", "Skating", "Golf"
];

const AREAS_BY_CITY: Record<string, string[]> = {
  Mumbai: [
    "Andheri West", "Andheri East", "Powai", "Malad West", "Malad East",
    "Bandra", "Juhu", "Borivali", "Kandivali", "Goregaon", "Kurla",
    "Thane", "Navi Mumbai", "Kharghar", "Nerul", "Vashi", "Dadar",
    "Chembur", "Mulund", "Vikhroli"
  ],
};

const CITIES = [
  "Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Ahmedabad", "Chennai",
  "Kolkata", "Pune", "Jaipur", "Surat", "Lucknow", "Kanpur", "Nagpur",
  "Indore", "Thane", "Bhopal", "Visakhapatnam", "Patna", "Vadodara",
  "Ghaziabad", "Ludhiana", "Agra", "Nashik", "Faridabad", "Meerut",
  "Rajkot", "Kalyan-Dombivli", "Vasai-Virar", "Varanasi", "Srinagar",
  "Aurangabad", "Dhanbad", "Amritsar", "Navi Mumbai", "Allahabad",
  "Ranchi", "Howrah", "Coimbatore", "Jabalpur", "Gwalior", "Vijayawada",
  "Jodhpur", "Madurai", "Raipur", "Kota", "Guwahati", "Chandigarh",
  "Thiruvananthapuram", "Solapur", "Hubballi-Dharwad", "Mysuru",
  "Tiruchirappalli", "Bareilly", "Aligarh", "Tiruppur", "Gurugram",
  "Moradabad", "Jalandhar", "Bhubaneswar", "Salem", "Warangal",
  "Guntur", "Bhiwandi", "Noida", "Jamshedpur", "Cuttack", "Kochi",
  "Dehradun", "Durgapur", "Ajmer", "Nellore", "Udaipur", "Shimla",
  "Panaji", "Puducherry"
];

export default function AddVenueModal({
  onClose,
  onSave,
  existingComplexNames = [],
}: {
  onClose: () => void;
  onSave: (venue: any) => void;
  existingComplexNames?: string[];
}) {
  const [form, setForm] = useState({
    complex_name: "",
    facility_label: "",
    name: "",
    city: "",
    area: "",
    sport_type: "",
    address: "",
    price_per_hour: "",
    description: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showComplexSuggestions, setShowComplexSuggestions] = useState(false);

  const filteredComplexNames = existingComplexNames.filter(c =>
    c.toLowerCase().includes(form.complex_name.toLowerCase())
  );

  const handleSave = async () => {
    if (!form.name || !form.city || !form.area || !form.sport_type || !form.price_per_hour) {
      setError("Please fill in all required fields");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const { getSupabaseAuth } = await import("@/lib/auth");
      const supabase = getSupabaseAuth();
      const { data: sessionData } = await supabase.auth.getSession();
      const token = sessionData?.session?.access_token;
      const userId = sessionData?.session?.user?.id;

      const res = await fetch("/api/venues", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          name: form.name,
          city: form.city,
          area: form.area,
          sport: form.sport_type,
          sport_type: form.sport_type,
          complex_name: form.complex_name || null,
          facility_label: form.facility_label || null,
          address: form.address,
          price_per_hour: parseInt(form.price_per_hour),
          description: form.description,
          is_active: true,
          owner_id: userId,
        }),
      });
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        onSave(data[0]);
        onClose();
      }
    } catch (e) {
      setError("Failed to save venue");
    }
    setLoading(false);
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 px-4">
      <div className="bg-[#16291C] border border-[#1E3324] rounded-xl w-full max-w-md max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#1E3324]">
          <h2 className="font-semibold text-[#F4F7ED]">Add New Venue</h2>
          <button onClick={onClose} className="text-[#9FB0A3] hover:text-[#F4F7ED]">
            <X size={20} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">

          {/* Complex Name */}
          <div className="relative">
            <label className="block text-xs text-[#9FB0A3] mb-1">
              Complex Name <span className="text-[#5C7066]">(optional — group multiple courts)</span>
            </label>
            <input
              value={form.complex_name}
              onChange={(e) => {
                setForm({ ...form, complex_name: e.target.value });
                setShowComplexSuggestions(true);
              }}
              onBlur={() => setTimeout(() => setShowComplexSuggestions(false), 200)}
              placeholder="e.g. Greenfield Sports Complex"
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
            />
            {showComplexSuggestions && filteredComplexNames.length > 0 && (
              <div className="absolute z-10 w-full bg-[#16291C] border border-[#2C4A33] rounded-lg mt-1">
                {filteredComplexNames.map(name => (
                  <button
                    key={name}
                    className="w-full text-left px-3 py-2 text-sm text-[#F4F7ED] hover:bg-[#1E3324]"
                    onClick={() => {
                      setForm({ ...form, complex_name: name });
                      setShowComplexSuggestions(false);
                    }}
                  >
                    {name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Facility Label */}
          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">
              Facility Label <span className="text-[#5C7066]">(optional — e.g. Turf 1, Pool A, Court 3)</span>
            </label>
            <input
              value={form.facility_label}
              onChange={(e) => setForm({ ...form, facility_label: e.target.value })}
              placeholder="e.g. Turf 1"
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
            />
          </div>

          {/* Venue Name */}
          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">Venue Name *</label>
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Greenfield Box Cricket Turf 1"
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
            />
          </div>

          {/* City */}
          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">City *</label>
            <select
              value={form.city}
              onChange={(e) => setForm({ ...form, city: e.target.value, area: "" })}
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm focus:outline-none focus:border-[#8BC34A]"
            >
              <option value="">Select city</option>
              {CITIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          {/* Sport Type */}
          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">Sport *</label>
            <select
              value={form.sport_type}
              onChange={(e) => setForm({ ...form, sport_type: e.target.value })}
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm focus:outline-none focus:border-[#8BC34A]"
            >
              <option value="">Select sport</option>
              {SPORTS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          {/* Area */}
          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">Area *</label>
            {form.city && AREAS_BY_CITY[form.city] ? (
              <select
                value={form.area}
                onChange={(e) => setForm({ ...form, area: e.target.value })}
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm focus:outline-none focus:border-[#8BC34A]"
              >
                <option value="">Select area</option>
                {AREAS_BY_CITY[form.city].map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            ) : (
              <input
                value={form.area}
                onChange={(e) => setForm({ ...form, area: e.target.value })}
                placeholder={form.city ? "e.g. Koramangala" : "Select a city first"}
                disabled={!form.city}
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A] disabled:opacity-50"
              />
            )}
          </div>

          {/* Address */}
          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">Full Address</label>
            <input
              value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })}
              placeholder="e.g. Link Road, Andheri West, Mumbai 400058"
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
            />
          </div>

          {/* Price */}
          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">Price per hour (₹) *</label>
            <input
              type="number"
              value={form.price_per_hour}
              onChange={(e) => setForm({ ...form, price_per_hour: e.target.value })}
              placeholder="e.g. 1400"
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="e.g. Floodlit turf, parking available, changing rooms"
              rows={3}
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A] resize-none"
            />
          </div>

          {error && <p className="text-[#E5484D] text-xs">{error}</p>}

          <div className="flex gap-3 pt-2">
            <button
              onClick={onClose}
              className="flex-1 border border-[#2C4A33] text-[#9FB0A3] py-2.5 rounded-lg text-sm hover:border-[#8BC34A] transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={loading}
              className="flex-1 bg-[#8BC34A] text-[#0E1F14] py-2.5 rounded-lg text-sm font-medium hover:bg-[#9BCF5E] transition-colors disabled:opacity-50"
            >
              {loading ? "Saving..." : "Save Venue"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
