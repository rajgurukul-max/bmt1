# BookMyTurfs — Owner Console

Owner-facing dashboard for managing turf venues, slot availability, bookings, and payouts.
Currently runs on mock data in `src/lib/data.ts` — swap that file for real API calls when your
backend is ready and nothing else needs to change.

## Project structure

```
src/
  app/
    layout.tsx       # root layout, fonts, metadata
    page.tsx          # main dashboard page, wires everything together
    globals.css        # Tailwind + font imports
  components/
    Sidebar.tsx         # left nav
    Header.tsx           # top bar with date + "Add venue"
    StatCard.tsx          # small metric cards
    BookingList.tsx        # booking rows (dashboard + bookings tab)
    SlotCalendar.tsx        # the slot grid — tap to block/unblock
    PayoutsPanel.tsx         # payouts summary
  lib/
    data.ts                  # mock venues, bookings, slot data — replace with API calls later
```

## Run locally

```bash
npm install
npm run dev
```

Open http://localhost:3000

## Deploy to bookmyturfs.com (Vercel — recommended, free tier)

1. Push this folder to a GitHub repo:
   ```bash
   git init
   git add .
   git commit -m "Owner dashboard MVP"
   git branch -M main
   git remote add origin https://github.com/<your-username>/bookmyturfs-dashboard.git
   git push -u origin main
   ```
2. Go to https://vercel.com → sign up with GitHub → "Add New Project" → import this repo → Deploy.
   You'll get a live URL like `bookmyturfs-dashboard.vercel.app` within ~2 minutes.
3. In the Vercel project: **Settings → Domains → Add** → type `bookmyturfs.com` → Add.
4. Vercel will show you DNS records to add (usually an A record pointing to `76.76.21.21`
   and a CNAME for `www`). Copy these.
5. Go to your domain registrar (GoDaddy, Namecheap, etc.) → DNS settings for bookmyturfs.com →
   paste in the records Vercel gave you.
6. Wait 10 minutes–few hours for DNS to propagate. Vercel auto-issues an SSL certificate once it
   detects the domain is pointed correctly — your site will be live at `https://bookmyturfs.com`.

Every time you `git push` after this, Vercel auto-redeploys. No manual re-upload ever needed.

## Connecting real data later

Replace the contents of `src/lib/data.ts` with functions that call your backend API
(e.g. `fetch('/api/venues')`) instead of returning hardcoded arrays. Because every component
reads from this one file, the rest of the app doesn't need to change.
