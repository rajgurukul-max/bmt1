import { LucideIcon } from "lucide-react";

export default function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
}) {
  return (
    <div className="bg-pitch-surface border border-pitch-border rounded-lg p-5">
      <div className="flex items-center gap-2 text-muted text-xs uppercase tracking-wide mb-3">
        <Icon size={14} /> {label}
      </div>
      <div className="text-2xl font-mono font-semibold text-chalk">{value}</div>
    </div>
  );
}
