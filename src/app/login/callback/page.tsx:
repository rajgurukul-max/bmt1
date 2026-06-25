"use client";

import { useEffect } from "react";
import { getSupabaseAuth } from "@/lib/auth";

export default function CallbackPage() {
  useEffect(() => {
    const handleCallback = async () => {
      const supabase = getSupabaseAuth();
      const { data, error } = await supabase.auth.getSession();
      
      if (data?.session) {
        window.location.href = "/";
      } else {
        // Handle hash fragment token
        const hash = window.location.hash;
        if (hash && hash.includes("access_token")) {
          const params = new URLSearchParams(hash.substring(1));
          const access_token = params.get("access_token");
          const refresh_token = params.get("refresh_token");
          
          if (access_token && refresh_token) {
            await supabase.auth.setSession({
              access_token,
              refresh_token,
            });
            window.location.href = "/";
          }
        } else {
          window.location.href = "/login";
        }
      }
    };

    handleCallback();
  }, []);

  return (
    <div className="min-h-screen bg-[#0E1F14] flex items-center justify-center">
      <p className="text-[#8BC34A] font-mono animate-pulse">
        Signing you in...
      </p>
    </div>
  );
}
