"use client";

import { useEffect, useState } from "react";
import { Plus, Tag, Copy, Check } from "lucide-react";

export default function PromosPanel() {
  const [promos, setPromos] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [copiedCode, setCopiedCode] = useState("");

  const [form, setForm] = useState({
    code: "",
    discount_type: "percent",
    discount_value: "",
    min_amount: "",
    max_uses: "",
    expires_at: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const fetchPromos = () => {
    setLoading(true);
    fetch("/api/promos")
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) setPromos(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    fetchPromos();
  }, []);

  const handleSave = async () => {
    if (!form.code || !form.discount_value) {
      setError("Code and discount value are required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const res = await fetch("/api/promos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        setForm({
          code: "",
          discount_type: "percent",
          discount_value: "",
          min_amount: "",
          max_uses: "",
          expires_at: "",
        });
        setShowForm(false);
        fetchPromos();
      }
    } catch (e) {
      setError("Failed to create promo code");
    }
    setSaving(false);
  };

  const toggleActive = async (id: string, current: boolean) => {
    setPromos((prev) =>
      prev.map((p) => (p.id === id ? { ...p, is_active: !current } : p))
    );
    await fetch("/api/promos", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, is_active: !current }),
    });
  };

  const copyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(""), 1500);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-sm font-medium text-[#9FB0A3] uppercase tracking-wide">
          Promo Codes
        </h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-2 bg-[#8BC34A] text-[#0E1F14] text-sm font-medium px-4 py-2 rounded-md hover:bg-[#9BCF5E] transition-colors"
        >
          <Plus size={16} /> New Promo
        </button>
      </div>

      {showForm && (
        <div className="bg-[#16291C] border border-[#1E3324] rounded-lg p-6 mb-6 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-[#9FB0A3] mb-1">Code *</label>
              <input
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
                placeholder="e.g. FIRST50"
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
              />
            </div>

            <div>
              <label className="block text-xs text-[#9FB0A3] mb-1">Discount Type *</label>
              <select
                value={form.discount_type}
                onChange={(e) => setForm({ ...form, discount_type: e.target.value })}
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm focus:outline-none focus:border-[#8BC34A]"
              >
                <option value="percent">Percent off (%)</option>
                <option value="flat">Flat amount off (₹)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-[#9FB0A3] mb-1">
                Discount Value * {form.discount_type === "percent" ? "(%)" : "(₹)"}
              </label>
              <input
                type="number"
                value={form.discount_value}
                onChange={(e) => setForm({ ...form, discount_value: e.target.value })}
                placeholder={form.discount_type === "percent" ? "e.g. 10" : "e.g. 100"}
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
              />
            </div>

            <div>
              <label className="block text-xs text-[#9FB0A3] mb-1">
                Minimum Order Amount (₹)
              </label>
              <input
                type="number"
                value={form.min_amount}
                onChange={(e) => setForm({ ...form, min_amount: e.target.value })}
                placeholder="e.g. 500 (optional)"
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
              />
            </div>

            <div>
              <label className="block text-xs text-[#9FB0A3] mb-1">Max Uses</label>
              <input
                type="number"
                value={form.max_uses}
                onChange={(e) => setForm({ ...form, max_uses: e.target.value })}
                placeholder="Leave blank for unlimited"
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A]"
              />
            </div>

            <div>
              <label className="block text-xs text-[#9FB0A3] mb-1">Expires On</label>
              <input
                type="date"
                value={form.expires_at}
                onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-3 py-2.5 text-[#F4F7ED] text-sm focus:outline-none focus:border-[#8BC34A]"
              />
            </div>
          </div>

          {error && <p className="text-[#E5484D] text-xs">{error}</p>}

          <div className="flex gap-3">
            <button
              onClick={() => setShowForm(false)}
              className="flex-1 border border-[#2C4A33] text-[#9FB0A3] py-2.5 rounded-lg text-sm hover:border-[#8BC34A] transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex-1 bg-[#8BC34A] text-[#0E1F14] py-2.5 rounded-lg text-sm font-medium hover:bg-[#9BCF5E] transition-colors disabled:opacity-50"
            >
              {saving ? "Saving..." : "Create Promo Code"}
            </button>
          </div>
        </div>
      )}

      <div className="bg-[#16291C] border border-[#1E3324] rounded-lg p-6">
        {loading ? (
          <p className="text-[#5C7066] text-sm">Loading promo codes...</p>
        ) : promos.length === 0 ? (
          <p className="text-[#5C7066] text-sm">
            No promo codes yet — create one to offer discounts to your customers.
          </p>
        ) : (
          <div className="space-y-3">
            {promos.map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between border border-[#1E3324] rounded-lg px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <div className="bg-[#8BC34A]/20 text-[#8BC34A] p-2 rounded-md">
                    <Tag size={16} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-semibold text-[#F4F7ED]">
                        {p.code}
                      </span>
                      <button
                        onClick={() => copyCode(p.code)}
                        className="text-[#5C7066] hover:text-[#8BC34A] transition-colors"
                      >
                        {copiedCode === p.code ? <Check size={14} /> : <Copy size={14} />}
                      </button>
                    </div>
                    <p className="text-xs text-[#9FB0A3] mt-0.5">
                      {p.discount_type === "percent"
                        ? `${p.discount_value}% off`
                        : `₹${p.discount_value} off`}
                      {p.min_amount > 0 && ` · min ₹${p.min_amount}`}
                      {p.max_uses && ` · ${p.used_count || 0}/${p.max_uses} used`}
                      {p.expires_at &&
                        ` · expires ${new Date(p.expires_at).toLocaleDateString("en-IN")}`}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => toggleActive(p.id, p.is_active)}
                  className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                    p.is_active
                      ? "border-[#8BC34A]/30 text-[#8BC34A] bg-[#8BC34A]/10"
                      : "border-[#2C4A33] text-[#5C7066]"
                  }`}
                >
                  {p.is_active ? "Active" : "Disabled"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
