import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BookMyTurfs — Owner Console",
  description: "Manage your turf bookings, slots, and payouts.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="font-sans">{children}</body>
    </html>
  );
}
