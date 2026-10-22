"""Live BUY / SELL / EXIT alerts for the Nifty 'EMA ribbon' intraday rule with
the market-type switch. SIGNALS ONLY -- this script never places orders.

Rule (10-minute candles, same code as ribbon_trend_backtest.py):
  BUY   close > EMA9 > EMA21 > EMA50, RSI(14) > 60, MACD histogram > 0 and rising
  SELL  close < EMA9 < EMA21 < EMA50, RSI(14) < 40, MACD histogram < 0 and falling
  STOP  60 Nifty points from the signal price
  EXIT  a 10-min candle closes back through EMA21, the stop is touched, or 15:10
  Entries 09:35-14:30, at most 2 signals a day. After a stop-loss, no more
  signals in that same direction for the rest of the day (1-year test: total
  +2,237 -> +2,457 pts, max drawdown 442 -> 380, better in both halves).
Market-type switch, decided at the open from the previous 5 days:
  TRENDING (4+ of them had a first hour >= 120 pts) -> signals from 09:35
  QUIET    -> signals only after 10:15, and only if TODAY's first hour >= 120 pts
Backtest (Sep 2025 - Oct 2026): ~104 signals, about +22 points per signal on
average after costs; a 50-80 point stop all gave similar results.

Alerts go to the terminal/log and, if a topic is set, to your phone through the
free ntfy app (https://ntfy.sh): install ntfy, subscribe to a hard-to-guess
topic name, and pass it with --ntfy TOPIC (or NTFY_TOPIC=... in .env).

Run on the VPS each trading day (it waits for the morning token):
    12 9 * * 1-5  cd /home/ubuntu/bmt1/trading && flock -n /tmp/ribbon.lock ~/venv/bin/python nifty_ribbon_signals.py >> logs/ribbon_signals.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time as time_module
from datetime import datetime, timedelta

import pandas as pd

import condor_live_core as core
import ribbon_trend_backtest as rb
from config import BASE_DIR

logger = logging.getLogger("ribbon_signals")

NIFTY_TOKEN = 256265          # NSE:NIFTY 50 index
STATE_FILE = BASE_DIR / "logs" / "ribbon_signal_state.json"
SIGNALS_CSV = BASE_DIR / "logs" / "ribbon_signals.csv"
STOP_PTS = 60.0
RSI_BUY, RSI_SELL = 60.0, 40.0   # 1-year test: 55/45 made 167 pts less (2,290 vs 2,457)
FIRST_HOUR_MIN = 120.0
TREND_DAYS, TREND_NEEDED = 5, 4
MAX_SIGNALS = 2
EXIT_HHMM = "15:10"
POLL_S = 20


class Alerts:
    def __init__(self, topic: str | None):
        self.topic = topic

    def send(self, kind: str, title: str, body: str) -> None:
        icon = {"BUY": "🟢🟢🟢 BUY", "SELL": "🔴🔴🔴 SELL", "EXIT": "⚪⚪⚪ EXIT", "INFO": "ℹ️  INFO"}[kind]
        bar = "=" * 70
        logger.warning("\n%s\n%s  %s\n%s\n%s", bar, icon, title, body, bar)
        core.append_csv({"time_ist": core.now_ist().strftime("%Y-%m-%d %H:%M:%S"), "kind": kind,
                         "title": title, "body": body.replace("\n", " | ")}, SIGNALS_CSV)
        if not self.topic:
            return
        try:
            import requests
            requests.post(f"https://ntfy.sh/{self.topic}", data=body.encode("utf-8"), timeout=10, headers={
                "Title": f"{kind}: {title}".encode("utf-8"),
                "Priority": "5" if kind in ("BUY", "SELL", "EXIT") else "3",
                "Tags": {"BUY": "green_circle", "SELL": "red_circle", "EXIT": "white_circle"}.get(kind, "information_source"),
            })
        except Exception as exc:
            logger.warning("Phone alert failed (%s) -- the terminal/log alert above still stands.", exc)


class Engine:
    """Feed it 5-minute candles + the latest price; it emits alerts. Pure logic,
    so it can be tested without Kite."""

    def __init__(self, alerts: Alerts, state: dict | None = None):
        self.alerts = alerts
        self.s = state or {}

    def _today(self, day: str) -> dict:
        if self.s.get("day") != day:
            self.s = {"day": day, "signals": 0, "pos": None, "last_bar": None, "announced": False,
                      "hour1_announced": False,
                      "stopped": [], "block_announced": []}
        return self.s

    def step(self, now: datetime, five_min: pd.DataFrame, ltp: float | None) -> None:
        day = now.date()
        st = self._today(day.isoformat())
        # only COMPLETED candles: a 10-min candle that started at t is done at t+10
        b = rb.bars10(five_min)
        b = b[b.ts + pd.Timedelta(minutes=10) <= pd.Timestamp(now)].reset_index(drop=True)
        f = rb.day_features(five_min, None)
        wide = (f["hour1_range"] >= FIRST_HOUR_MIN).astype(int)
        prev = wide[wide.index < day].tail(TREND_DAYS)
        trending = len(prev) == TREND_DAYS and prev.sum() >= TREND_NEEDED
        today_bars = b[b.day == day]

        if not st["announced"]:
            st["announced"] = True
            if trending:
                msg = (f"Market type: TRENDING ({int(prev.sum())}/{TREND_DAYS} recent days had a first hour >= "
                       f"{FIRST_HOUR_MIN:.0f} pts). Signals allowed from 09:35.")
            else:
                msg = (f"Market type: QUIET ({int(prev.sum())}/{TREND_DAYS} recent days had a wide first hour). "
                       f"Signals only after 10:15 and only if today's first hour >= {FIRST_HOUR_MIN:.0f} pts.")
            self.alerts.send("INFO", f"Nifty ribbon signals {day}", msg)
        h1 = f["hour1_range"].get(day) if day in f.index else None
        if not trending and not st["hour1_announced"] and now.strftime("%H:%M") >= "10:15" and h1 is not None:
            st["hour1_announced"] = True
            ok = h1 >= FIRST_HOUR_MIN
            self.alerts.send("INFO", f"First hour range {h1:.0f} pts",
                             "Today qualifies -- signals are ON for the rest of the day." if ok else
                             "Below 120 pts -- no signals today (quiet day).")

        pos = st["pos"]
        # stop check on every poll, using the live price
        if pos and ltp is not None:
            side = pos["side"]
            if (side > 0 and ltp <= pos["stop"]) or (side < 0 and ltp >= pos["stop"]):
                self._exit(st, ltp, f"STOP HIT at {ltp:.0f} (stop {pos['stop']:.0f})")
                st.setdefault("stopped", []).append(side)
                return
        if pos and now.strftime("%H:%M") >= EXIT_HHMM:
            self._exit(st, ltp if ltp is not None else float(today_bars.close.iloc[-1]), "15:10 time exit")
            return

        if today_bars.empty or len(b) < 2:
            return
        last = b.iloc[-1]
        if st["last_bar"] == str(last.ts) or last.day != day:
            return
        st["last_bar"] = str(last.ts)
        prevb = b.iloc[-2]
        if pos:
            side = pos["side"]
            if (side > 0 and last.close < last.e21) or (side < 0 and last.close > last.e21):
                self._exit(st, float(last.close), f"10-min candle closed {'below' if side > 0 else 'above'} "
                                                   f"EMA21 ({last.e21:.0f})")
            return
        hhmm = last.hhmm
        if not ("09:35" <= hhmm < "14:30") or st["signals"] >= MAX_SIGNALS:
            return
        if not trending and not (hhmm >= "10:15" and h1 is not None and h1 >= FIRST_HOUR_MIN):
            return
        lg = last.close > last.e9 > last.e21 > last.e50 and last.rsi > RSI_BUY and last.mh > 0 and last.mh > prevb.mh
        sh = last.close < last.e9 < last.e21 < last.e50 and last.rsi < RSI_SELL and last.mh < 0 and last.mh < prevb.mh
        if not (lg or sh):
            return
        side = 1 if lg else -1
        if side in st.setdefault("stopped", []):
            if side not in st.setdefault("block_announced", []):
                st["block_announced"].append(side)
                what = "BUY" if side > 0 else "SELL"
                self.alerts.send("INFO", f"{what} signal skipped at {last.close:.0f}",
                                 f"A {what} already hit its stop today -- no more {what}s today "
                                 f"(the opposite side is still allowed).")
            return
        px = float(last.close)
        stop = px - side * STOP_PTS
        st["pos"] = {"side": side, "entry": px, "stop": stop, "time": now.strftime("%H:%M")}
        st["signals"] += 1
        what = "BUY" if side > 0 else "SELL"
        self.alerts.send(what, f"Nifty {what} at {px:.0f}  (signal {st['signals']}/{MAX_SIGNALS} today)",
                         f"Candle {hhmm}: close {px:.0f}, EMA9/21/50 {last.e9:.0f}/{last.e21:.0f}/{last.e50:.0f}, "
                         f"RSI {last.rsi:.0f}, MACD hist {last.mh:+.1f}\n"
                         f"STOP {stop:.0f} ({STOP_PTS:.0f} pts). Exit when a 10-min candle closes "
                         f"{'below' if side > 0 else 'above'} EMA21 (now {last.e21:.0f}), or at 15:10.\n"
                         f"Futures: {'buy' if side > 0 else 'sell'} Nifty fut | Options: buy ATM "
                         f"{'CE' if side > 0 else 'PE'}.")

    def _exit(self, st: dict, px: float, why: str) -> None:
        pos = st["pos"]
        pts = (px - pos["entry"]) * pos["side"]
        self.alerts.send("EXIT", f"Exit {'long' if pos['side'] > 0 else 'short'} at {px:.0f}  ({pts:+.0f} pts)",
                         f"{why}. Entry {pos['entry']:.0f} at {pos['time']}.")
        st["pos"] = None


def fetch_5min(kite, now: datetime) -> pd.DataFrame:
    rows = kite.historical_data(NIFTY_TOKEN, now - timedelta(days=20), now, "5minute")
    d = pd.DataFrame(rows)
    d["ts"] = pd.to_datetime(d["date"])
    if d["ts"].dt.tz is None:
        d["ts"] = d["ts"].dt.tz_localize(core.IST)
    d = d[["ts", "open", "high", "low", "close"]]
    return d[d.ts + pd.Timedelta(minutes=5) <= pd.Timestamp(now)]   # drop the candle still forming


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ntfy", default=None, help="ntfy.sh topic for phone alerts (or NTFY_TOPIC in .env)")
    ap.add_argument("--test-alert", action="store_true", help="send one test alert and exit")
    args = ap.parse_args()
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    alerts = Alerts(args.ntfy or os.environ.get("NTFY_TOPIC"))
    if args.test_alert:
        alerts.send("BUY", "TEST alert -- not a real signal", "If you see this on your phone, alerts work.")
        return
    if not core.is_trading_day(core.now_ist().date(), core.load_holidays()):
        logger.info("Exchange holiday -- no signals today.")
        return
    kite = core.connect_when_token_valid()
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else None
    eng = Engine(alerts, state)
    logger.info("Watching Nifty for ribbon signals until 15:30 (signals only, no orders).")
    while core.now_ist().time() < core.MARKET_CLOSE:
        now = core.now_ist()
        if now.time() < core.MARKET_OPEN:
            time_module.sleep(30)
            continue
        try:
            five = fetch_5min(kite, now)
            ltp = kite.ltp(["NSE:NIFTY 50"])["NSE:NIFTY 50"]["last_price"]
            eng.step(now, five, ltp)
            STATE_FILE.write_text(json.dumps(eng.s))
        except Exception as exc:
            logger.warning("Poll failed (%s) -- retrying.", exc)
        time_module.sleep(POLL_S)
    logger.info("Market closed -- done for today.")


if __name__ == "__main__":
    main()
