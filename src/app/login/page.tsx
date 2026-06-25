"use client";

import { useState, useEffect } from "react";
import { getSupabaseAuth } from "@/lib/auth";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  // Handle magic link token in URL hash
  useEffect(() => {
    const hash = window.location.hash;
    const search = window.location.search;
    
    if (hash && hash.includes("access_token")) {
      const params = new URLSearchParams(hash.substring(1));
      const access_token = params.get("access_token");
      const refresh_token = params.get("refresh_token");
      if (access_token && refresh_token) {
        const supabase = getSupabaseAuth();
        supabase.auth.setSession({ access_token, refresh_token })
          .then(() => { window.location.href = "/"; });
      }
    }
    
    if (search && search.includes("code=")) {
      const params = new URLSearchParams(search);
      const code = params.get("code");
      if (code) {
        const supabase = getSupabaseAuth();
        supabase.auth.exchangeCodeForSession(code)
          .then(() => { window.location.href = "/"; });
      }
    }
  }, []);


  const sendMagicLink = async () => {
    if (!email) return;
    setLoading(true);
    setError("");
    const supabase = getSupabaseAuth();
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: "https://www.bookmyturfs.com/login",
        shouldCreateUser: true,
      },
    });
    if (error) {
      setError(error.message);
    } else {
      setSent(true);
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
          {!sent ? (
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
              {error && (
                <p className="text-[#E5484D] text-xs mb-3">{error}</p>
              )}
              <button
                onClick={sendMagicLink}
                disabled={loading || !email}
                className="w-full bg-[#8BC34A] text-[#0E1F14] font-medium py-3 rounded-lg hover:bg-[#9BCF5E] transition-colors disabled:opacity-50"
              >
                {loading ? "Sending..." : "Send Login Link"}
              </button>
            </>
          ) : (
            <div className="text-center py-4">
              <div className="text-4xl mb-4">📧</div>
              <h2 className="text-[#F4F7ED] font-medium mb-2">
                Check your email!
              </h2>
              <p className="text-[#9FB0A3] text-sm mb-4">
                We sent a login link to{" "}
                <span className="text-[#8BC34A]">{email}</span>
              </p>
              <p className="text-[#5C7066] text-xs mb-4">
                Click the link in your email to access your dashboard.
                Link expires in 1 hour.
              </p>
              <button
                onClick={() => {
                  setSent(false);
                  setEmail("");
                }}
                className="text-[#9FB0A3] text-sm hover:text-[#F4F7ED]"
              >
                ← Try different email
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
