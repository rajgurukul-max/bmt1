"use client";
import { useState } from "react";
import { X } from "lucide-react";

const SPORTS = ["Cricket", "Football", "Badminton", "Tennis", "Basketball"];
const AREAS = ["Andheri West", "Andheri East", "Powai", "Malad West", "Malad East", "Bandra", "Juhu", "Borivali", "Kandivali", "Goregaon", "Kurla", "Thane", "Navi Mumbai"];

export default function AddVenueModal({
  onClose,
  onSave,
}: {
  onClose: () => void;
  onSave: (venue: any) => void;
}) {
  const [form, setForm] = useState({
    name: "",
    area: "",
    sport: "",
    address: "",
    price_per_hour: "",
    description: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSave = async () => {
    if (!form.name || !form.area || !form.sport || !form.price_per_hour) {
      setError("Please fill in all required fields");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/venues", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          price_per_hour: parseInt(form.price_per_hour),
          is_active: true,
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
          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">Venue Name *</label>
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Greenfield Box Cricket"
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
            />
          </div>

          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">Sport *</label>
            <select
              value={form.sport}
              onChange={(e) => setForm({ ...form, sport: e.target.value })}
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm focus:outline-none focus:border-[#8BC34A]"
            >
              <option value="">Select sport</option>
              {SPORTS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">Area *</label>
            <select
              value={form.area}
              onChange={(e) => setForm({ ...form, area: e.target.value })}
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm focus:outline-none focus:border-[#8BC34A]"
            >
              <option value="">Select area</option>
              {AREAS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-xs text-[#9FB0A3] mb-1">Full Address</label>
            <input
              value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })}
              placeholder="e.g. Link Road, Andheri West, Mumbai"
              className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
            />
          </div>

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
