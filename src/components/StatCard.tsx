import { LucideIcon } from "lucide-react";

export default function StatCard({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string | number }) {
  return (
    <div className="bg-[#16291C] border border-[#1E3324] rounded-lg p-5">
      <div className="flex items-center gap-2 text-[#9FB0A3] text-xs uppercase tracking-wide mb-3">
        <Icon size={14} /> {label}
      </div>
      <div className="text-2xl font-mono font-semibold text-[#F4F7ED]">{value}</div>
    </div>
  );
}
