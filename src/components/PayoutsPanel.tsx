import { Wallet } from "lucide-react";

export default function PayoutsPanel() {
  return (
    <div className="bg-[#16291C] border border-[#1E3324] rounded-lg p-8 text-center">
      <Wallet size={28} className="mx-auto mb-3 text-[#8BC34A]" />
      <p className="text-2xl font-mono font-semibold">₹48,260</p>
      <p className="text-sm text-[#9FB0A3] mt-1">Next payout: Friday, to account ending 4821</p>
      <p className="text-xs text-[#5C7066] mt-4">Connects to Razorpay once backend is live.</p>
    </div>
  );
}
