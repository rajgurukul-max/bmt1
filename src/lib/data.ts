export type Venue = { id: string; name: string; area: string; sport: string };
export type Booking = { id: string; venue: string; name: string; time: string; date: string; amount: number; status: "confirmed" | "pending"; players: number };
export type SlotStatus = "open" | "booked" | "blocked";

export const VENUES: Venue[] = [
  { id: "v1", name: "Greenfield Box Cricket", area: "Andheri West", sport: "Cricket" },
  { id: "v2", name: "Powai Turf Arena", area: "Powai", sport: "Football" },
  { id: "v3", name: "Malad Smash Court", area: "Malad West", sport: "Badminton" },
];

export const HOURS = Array.from({ length: 14 }, (_, i) => 6 + i);

export function getNextDays(count: number): Date[] {
  const today = new Date();
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(today);
    d.setDate(d.getDate() + i);
    return d;
  });
}

export function dateLabel(d: Date): string {
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

export function seedSlots(venues: Venue[], days: Date[], hours: number[]): Record<string, SlotStatus> {
  const status: Record<string, SlotStatus> = {};
  venues.forEach((v) => {
    days.forEach((d) => {
      hours.forEach((h) => {
        const key = `${v.id}_${d.toDateString()}_${h}`;
        const r = Math.random();
        status[key] = r < 0.18 ? "booked" : r < 0.26 ? "blocked" : "open";
      });
    });
  });
  return status;
}

export const BOOKINGS: Booking[] = [
  { id: "BK1042", venue: "Greenfield Box Cricket", name: "Rohan Salvi", time: "7:00 PM - 8:00 PM", date: "Today", amount: 1400, status: "confirmed", players: 10 },
  { id: "BK1041", venue: "Powai Turf Arena", name: "Aisha Khan", time: "6:00 PM - 7:00 PM", date: "Today", amount: 2200, status: "confirmed", players: 14 },
  { id: "BK1039", venue: "Malad Smash Court", name: "Varun Mehta", time: "8:00 AM - 9:00 AM", date: "Tomorrow", amount: 600, status: "pending", players: 4 },
  { id: "BK1037", venue: "Greenfield Box Cricket", name: "Sneha Iyer", time: "9:00 PM - 10:00 PM", date: "Tomorrow", amount: 1400, status: "confirmed", players: 8 },
];
