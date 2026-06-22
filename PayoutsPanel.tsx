import { Wallet } from "lucide-react";

export default function PayoutsPanel() {
  return (
    <div className="bg-pitch-surface border border-pitch-border rounded-lg p-8 text-center">
      <Wallet size={28} className="mx-auto mb-3 text-turf" />
      <p className="text-2xl font-mono font-semibold">₹48,260</p>
      <p className="text-sm text-muted mt-1">Next payout: Friday, to account ending 4821</p>
      <p className="text-xs text-dim mt-4">
        Payout history and downloadable statements connect once Razorpay Route is wired to your live backend.
      </p>
    </div>
  );
}
