"use client";

import { useState } from "react";
import { getSupabaseAuth } from "@/lib/auth";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [success, setSuccess] = useState("");

  const handleLogin = async () => {
    if (!email || !password) return;
    setLoading(true);
    setError("");
    const supabase = getSupabaseAuth();
    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (error) {
      setError(error.message);
    } else {
      window.location.href = "/";
    }
    setLoading(false);
  };

  const handleRegister = async () => {
    if (!email || !password) return;
    setLoading(true);
    setError("");
    const supabase = getSupabaseAuth();
    const { error } = await supabase.auth.signUp({
      email,
      password,
    });
    if (error) {
      setError(error.message);
    } else {
      setSuccess("Account created! You can now log in.");
      setMode("login");
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
            {mode === "login" ? "Owner Login" : "Create Account"}
          </h1>
          <p className="text-[#9FB0A3] text-sm mt-2">
            {mode === "login"
              ? "Sign in to manage your venues"
              : "Register as a venue owner"}
          </p>
        </div>

        <div className="bg-[#16291C] border border-[#1E3324] rounded-xl p-6">
          {success && (
            <p className="text-[#8BC34A] text-sm mb-4 text-center">
              {success}
            </p>
          )}

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

          <label className="block text-sm text-[#9FB0A3] mb-2">
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            className="w-full bg-[#0E1F14] border border-[#2C4A33] rounded-lg px-4 py-3 text-[#F4F7ED] text-sm placeholder-[#5C7066] focus:outline-none focus:border-[#8BC34A] mb-4"
          />

          {error && (
            <p className="text-[#E5484D] text-xs mb-3">{error}</p>
          )}

          <button
            onClick={mode === "login" ? handleLogin : handleRegister}
            disabled={loading || !email || !password}
            className="w-full bg-[#8BC34A] text-[#0E1F14] font-medium py-3 rounded-lg hover:bg-[#9BCF5E] transition-colors disabled:opacity-50 mb-4"
          >
            {loading
              ? "Please wait..."
              : mode === "login"
              ? "Sign In"
              : "Create Account"}
          </button>

          <button
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError("");
              setSuccess("");
            }}
            className="w-full text-[#9FB0A3] text-sm hover:text-[#F4F7ED] transition-colors text-center"
          >
            {mode === "login"
              ? "New owner? Create account →"
              : "Already have account? Sign in →"}
          </button>
        </div>
      </div>
    </div>
  );
}
