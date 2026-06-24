"use client";

import { useState } from "react";
import { getSupabaseAuth } from "@/lib/auth";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [step, setStep] = useState<"email" | "otp">("email");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const sendOtp = async () => {
    if (!email) return;
    setLoading(true);
    setError("");
    const supabase = getSupabaseAuth();
    const { error } = await supabase.auth.signInWithOtp({ email });
    if (error) {
      setError(error.message);
    } else {
      setMessage(`OTP sent to ${email}`);
      setStep("otp");
    }
    setLoading(false);
  };

  const verifyOtp = async () => {
    if (!otp) return;
    setLoading(true);
    setError("");
    const supabase = getSupabaseAuth();
    const { error } = await supabase.auth.verifyOtp({
      email,
      token: otp,
      type: "email",
    });
    if (error) {
      setError(error.message);
    } else {
      window.location.href = "/";
    }
    setLoading(false);
  };

  return (
    <div className="min-h-screen bg-[#0E1F14] flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="font-mono text-[#8BC34A] text-sm tracking-[0.2em] uppercase mb-2">
            BookMyTurfs
          </div>
          <h1 className="text-2xl font-semibold text-[#F4F7ED]">
            Owner Login
          </h1>
          <p className="text-[#9FB0A3] text-sm mt-2">
            Sign in to manage your venues
          </p>
        </div>

        <div className="bg-[#16291C] border border-[#1E3324] rounded-xl p-6">
          {step === "email" ? (
            <>
              <label className="block text-sm text-[#9FB0A3] mb-2">
                Email address
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="owner@example.com"
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-4 py-3 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A] mb-4"
              />
              {error && <p className="text-[#E5484D] text-xs mb-3">{error}</p>}
              {message && <p className="text-[#8BC34A] text-xs mb-3">{message}</p>}
              <button
                onClick={sendOtp}
                disabled={loading || !email}
                className="w-full bg-[#8BC34A] text-[#0E1F14] font-medium py-3 rounded-lg hover:bg-[#9BCF5E] transition-colors disabled:opacity-50"
              >
                {loading ? "Sending OTP..." : "Send OTP"}
              </button>
            </>
          ) : (
            <>
              <p className="text-[#9FB0A3] text-sm mb-4">
                Enter the 6-digit OTP sent to{" "}
                <span className="text-[#8BC34A]">{email}</span>
              </p>
              <label className="block text-sm text-[#9FB0A3] mb-2">
                OTP Code
              </label>
              <input
                type="text"
                value={otp}
                onChange={(e) => setOtp(e.target.value)}
                placeholder="123456"
                maxLength={6}
                className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-4 py-3 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A] mb-4 font-mono tracking-widest text-center text-lg"
              />
              {error && <p className="text-[#E5484D] text-xs mb-3">{error}</p>}
              <button
                onClick={verifyOtp}
                disabled={loading || otp.length < 6}
                className="w-full bg-[#8BC34A] text-[#0E1F14] font-medium py-3 rounded-lg hover:bg-[#9BCF5E] transition-colors disabled:opacity-50 mb-3"
              >
                {loading ? "Verifying..." : "Verify OTP"}
              </button>
              <button
                onClick={() => { setStep("email"); setError(""); setOtp(""); }}
                className="w-full text-[#9FB0A3] text-sm hover:text-[#F4F7ED] transition-colors"
              >
                ← Back to email
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
