"""Live BUY / SELL / EXIT alerts for the Nifty 'EMA ribbon' intraday rule with
the market-type switch. Signals only, unless --live (real orders) is given.

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

Trading (each signal): BUY -> buy ATM CE, SELL -> buy ATM PE, --lots lots
(default 5), MIS product (Zerodha squares MIS off itself ~15:20 as a backstop);
the option is sold on the signal's EXIT (stop / EMA21 / 15:10). Without --live
the same trades are PAPER-traded at real option prices (no orders). Expiry =
the nearest weekly after today (never an expiry-day option); if that strike is
a leg of the open Nifty condor, one strike ITM is used instead so the two never
share a symbol. A file RIBBON_KILL_SWITCH stops new trades (exits still run).

Alerts go to the terminal/log and, if a topic is set, to your phone through the
free ntfy app (https://ntfy.sh): install ntfy, subscribe to a hard-to-guess
topic name, and pass it with --ntfy TOPIC (or NTFY_TOPIC=... in .env).

Run on the VPS each trading day (it waits for the morning token):
    12 9 * * 1-5  cd /home/ubuntu/bmt1/trading && flock -n /tmp/ribbon.lock ~/venv/bin/python nifty_ribbon_signals.py --live --lots 5 >> logs/ribbon_signals.log 2>&1
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
TRADES_CSV = BASE_DIR / "logs" / "ribbon_trades.csv"
KILL_SWITCH = BASE_DIR / "RIBBON_KILL_SWITCH"
CONDOR_STATE = BASE_DIR / "nifty_condor_state.json"
EXIT_TRIES = 3
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
        icon = {"BUY": "🟢🟢🟢 BUY", "SELL": "🔴🔴🔴 SELL", "EXIT": "⚪⚪⚪ EXIT", "INFO": "ℹ️  INFO",
                "ORDER": "✅ ORDER", "ERROR": "🚨🚨 ACTION NEEDED"}[kind]
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
                "Priority": "5" if kind in ("BUY", "SELL", "EXIT", "ORDER", "ERROR") else "3",
                "Tags": {"BUY": "green_circle", "SELL": "red_circle", "EXIT": "white_circle",
                         "ORDER": "white_check_mark", "ERROR": "rotating_light"}.get(kind, "information_source"),
            })
        except Exception as exc:
            logger.warning("Phone alert failed (%s) -- the terminal/log alert above still stands.", exc)


class OptionTrader:
    """Buys the ATM CE (long signal) / PE (short signal) and sells it on exit.
    live=False paper-trades at real option prices (place_and_wait dry run)."""

    def __init__(self, kite, alerts: Alerts, lots: int, live: bool):
        self.kite, self.alerts, self.lots, self.live = kite, alerts, lots, live
        self.tag = "LIVE" if live else "PAPER"
        self._chain: list[dict] | None = None
        self._chain_day = None

    def chain(self, today) -> list[dict]:
        if self._chain is None or self._chain_day != today:
            opts = [i for i in self.kite.instruments(core.EXCHANGE)
                    if i["name"] == "NIFTY" and i["segment"] == "NFO-OPT"]
            expiry = min(i["expiry"] for i in opts if i["expiry"] > today)
            self._chain, self._chain_day = [i for i in opts if i["expiry"] == expiry], today
        return self._chain

    def pick(self, side: int, spot: float, today) -> dict:
        typ = "CE" if side > 0 else "PE"
        ch = sorted((i for i in self.chain(today) if i["instrument_type"] == typ), key=lambda i: i["strike"])
        strikes = [i["strike"] for i in ch]
        k = core.nearest_strike(strikes, spot)
        condor = core.load_state(CONDOR_STATE) if CONDOR_STATE.exists() else None
        if condor and condor.expiry == ch[0]["expiry"].isoformat():
            taken = {l["strike"] for l in condor.legs if l["opt_type"] == typ}
            while k in taken:          # never trade a symbol the condor holds: step ITM
                k = strikes[strikes.index(k) + (-1 if typ == "CE" else 1)]
        return next(i for i in ch if i["strike"] == k)

    def enter(self, side: int, spot: float, now: datetime) -> dict | None:
        what = "BUY" if side > 0 else "SELL"
        if KILL_SWITCH.exists():
            self.alerts.send("INFO", f"{what} not traded (RIBBON_KILL_SWITCH)", "Signal only -- delete the "
                             "RIBBON_KILL_SWITCH file to trade again.")
            return None
        try:
            inst = self.pick(side, spot, now.date())
            sym, qty = inst["tradingsymbol"], int(inst["lot_size"]) * self.lots
            ltp = core.get_ltps(self.kite, [sym])[sym]
            need = ltp * qty * 1.03
            if self.live:
                try:
                    free = float(self.kite.margins("equity")["net"])
                except Exception as exc:
                    free = None
                    logger.warning("Could not read funds (%s) -- trying the order anyway.", exc)
                if free is not None and free < need:
                    self.alerts.send("ERROR", f"{what} NOT traded: not enough funds",
                                     f"{sym} x{qty} needs ~Rs {need:,.0f}, available Rs {free:,.0f}.")
                    return None
            try:
                _, px = core.place_and_wait(self.kite, sym, True, qty, not self.live, self.kite.PRODUCT_MIS)
                filled = qty
            except core.OrderNotFilled as exc:
                filled, px = exc.filled_qty, exc.avg_price
                if not filled:
                    self.alerts.send("ERROR", f"{what} order NOT filled -- no position",
                                     f"{sym} x{qty}: {exc}. Signal is still tracked; nothing to exit.")
                    return None
                self.alerts.send("ERROR", f"{what} order PART filled: {filled}/{qty}",
                                 f"{sym}: holding {filled} @ {px:.2f}; it will be sold on the exit signal.")
        except Exception as exc:
            self.alerts.send("ERROR", f"{what} order FAILED -- check Kite", f"{exc}. If an order shows in "
                             f"Kite, sell it yourself; this script is not tracking it.")
            return None
        t = {"symbol": sym, "qty": filled, "left": filled, "entry": px, "exit_value": 0.0,
             "side": side, "time": now.strftime("%H:%M"), "live": self.live, "warned": False}
        self.alerts.send("ORDER", f"{self.tag}: bought {filled} {sym} @ {px:.2f}",
                         f"Cost Rs {px * filled:,.0f}. It is sold automatically on the EXIT signal "
                         f"(stop / EMA21 / 15:10).")
        return t

    def held(self, symbol: str) -> int | None:
        """MIS quantity of `symbol` in the account now, None if Kite can't say."""
        try:
            return sum(int(p["quantity"]) for p in self.kite.positions()["net"]
                       if p["tradingsymbol"] == symbol and p.get("product") == "MIS")
        except Exception as exc:
            logger.warning("Could not read positions (%s) -- selling the recorded quantity.", exc)
            return None

    def exit(self, t: dict, why: str) -> bool:
        """Sell what is left; True when flat. Called again on later polls if not."""
        if t["live"] and t["left"] > 0:
            held = self.held(t["symbol"])
            if held is not None and held < t["left"]:      # you sold some/all yourself in Kite
                done = t["left"] - max(held, 0)
                t["left"], t["qty"] = max(held, 0), t["qty"] - done
                self.alerts.send("INFO", f"{done} {t['symbol']} already sold in Kite",
                                 f"Selling only the {t['left']} still held." if t["left"] else
                                 "Nothing left to sell -- that trade's P&L is in Kite, not in this log.")
                if t["qty"] == 0:
                    return True
        for _ in range(EXIT_TRIES):
            if t["left"] <= 0:
                break
            try:
                _, px = core.place_and_wait(self.kite, t["symbol"], False, t["left"], not t["live"],
                                            self.kite.PRODUCT_MIS)
                t["exit_value"] += px * t["left"]
                t["left"] = 0
            except core.OrderNotFilled as exc:
                t["exit_value"] += exc.avg_price * exc.filled_qty
                t["left"] -= exc.filled_qty
                logger.warning("Exit order not fully filled (%s) -- retrying.", exc)
            except Exception as exc:
                logger.warning("Exit order failed (%s) -- retrying.", exc)
        if t["left"] > 0:
            if not t["warned"]:
                t["warned"] = True
                self.alerts.send("ERROR", f"EXIT NOT DONE: {t['left']} {t['symbol']} still open",
                                 "Retrying every poll. If it stays open, SELL IT IN KITE NOW. (MIS is squared "
                                 "off by Zerodha around 15:20 as a last resort.)")
            return False
        sold = t["qty"]
        exit_px = t["exit_value"] / sold
        pnl = t["exit_value"] - t["entry"] * sold
        self.alerts.send("ORDER", f"{'LIVE' if t['live'] else 'PAPER'}: sold {sold} {t['symbol']} @ {exit_px:.2f}"
                         f"  P&L Rs {pnl:+,.0f}", f"{why}. Bought @ {t['entry']:.2f} at {t['time']}.")
        core.append_csv({"date": core.now_ist().strftime("%Y-%m-%d"), "mode": "LIVE" if t["live"] else "PAPER",
                         "symbol": t["symbol"], "qty": sold, "entry_time": t["time"],
                         "exit_time": core.now_ist().strftime("%H:%M"), "entry": round(t["entry"], 2),
                         "exit": round(exit_px, 2), "pnl_rs": round(pnl), "why": why}, TRADES_CSV)
        return True


class Engine:
    """Feed it 5-minute candles + the latest price; it emits alerts. Pure logic,
    so it can be tested without Kite."""

    def __init__(self, alerts: Alerts, state: dict | None = None, trader: OptionTrader | None = None):
        self.alerts = alerts
        self.s = state or {}
        self.trader = trader

    def _today(self, day: str) -> dict:
        if self.s.get("day") != day:
            self.s = {"day": day, "signals": 0, "pos": None, "last_bar": None, "announced": False,
                      "hour1_announced": False,
                      "stopped": [], "block_announced": [], "trade": None}
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
        if self.trader and st.get("trade") and not pos:      # an earlier exit did not complete
            if self.trader.exit(st["trade"], "retried exit"):
                st["trade"] = None
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
        if not ("09:35" <= hhmm < "14:30") or st["signals"] >= MAX_SIGNALS or st.get("trade"):
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
        if self.trader:
            st["trade"] = self.trader.enter(side, ltp if ltp is not None else px, now)

    def _exit(self, st: dict, px: float, why: str) -> None:
        pos = st["pos"]
        pts = (px - pos["entry"]) * pos["side"]
        self.alerts.send("EXIT", f"Exit {'long' if pos['side'] > 0 else 'short'} at {px:.0f}  ({pts:+.0f} pts)",
                         f"{why}. Entry {pos['entry']:.0f} at {pos['time']}.")
        st["pos"] = None
        if self.trader and st.get("trade"):
            if self.trader.exit(st["trade"], why):
                st["trade"] = None


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
    ap.add_argument("--live", action="store_true", help="place REAL orders (default: paper trades)")
    ap.add_argument("--lots", type=int, default=5, help="option lots per signal (default 5)")
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
    today = core.now_ist().date().isoformat()
    if state and (state.get("trade") or {}).get("live") and state.get("day") != today:
        old = BASE_DIR / "logs" / f"ribbon_trade_unclosed_{state['day']}.json"
        old.write_text(json.dumps(state))
        t = state["trade"]
        alerts.send("ERROR", f"{t['symbol']} from {state['day']} may still be open",
                    f"The script did not record its exit ({t['left']} qty). Check Kite positions. Saved to {old.name}.")
    trader = OptionTrader(kite, alerts, args.lots, args.live)
    eng = Engine(alerts, state, trader)
    mode = (f"LIVE ORDERS: {args.lots} lots ATM CE/PE per signal" if args.live
            else f"PAPER trades ({args.lots} lots), no orders")
    alerts.send("INFO", f"Ribbon {'LIVE' if args.live else 'paper'} trading started",
                f"{mode}. Max 2 signals a day, exits on stop / EMA21 / 15:10.")
    logger.info("Watching Nifty for ribbon signals until 15:30 (%s).", mode)
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
