"""Backtest the user-specified weekly Nifty Iron Condor against REAL NSE options
settlement prices (not a Black-Scholes approximation).

Strategy (as specified): every Thursday, sell a CE 200 points above CMP and buy a
CE 400 points above CMP; sell a PE 200 points below CMP and buy a PE 400 points
below CMP; hold to the following Tuesday's expiry.

Data source: daily NSE F&O bhavcopy (real settlement prices, one row per
strike/expiry/day) mirrored from github.com/SantoshSrinivas79/NSE-FNO-Data-bank,
cached locally at data_cache/NIFTY_OPTIONS_bhavcopy.csv by
download_nifty_options.py (not included here -- see that script to refresh).

Known limitation, disclosed rather than hidden: this data is END-OF-DAY only (one
OHLC per contract per day), not intraday. So "enter Thursday 9:25am" is
approximated as entering at Thursday's CLOSE (both the underlying level used to
pick strikes, and the option's own closing premium), and "exit 3pm Tuesday" as
exiting at the expiry day's close. This shifts the effective entry time from
morning to end-of-day and can't capture intraday premium swings, but every price
used is a real traded/settled price, not a model.

Usage:
    python nifty_iron_condor_backtest.py
"""
from __future__ import annotations

import pandas as pd

DATA_PATH = "data_cache/NIFTY_OPTIONS_bhavcopy.csv"

# Approximate F&O cost model (Zerodha-style, as of recent years). Kept separate
# from costs.py's equity-specific model since F&O charges differ materially.
BROKERAGE_PER_ORDER = 20.0       # flat, or 0.03% of premium value, whichever lower
BROKERAGE_PCT = 0.03
STT_SELL_PCT = 0.1               # options STT, sell side only, on premium value
EXCHANGE_TXN_PCT = 0.053         # NSE F&O transaction charges, both sides, on premium value
SEBI_PCT = 0.0001
GST_PCT = 18.0
STAMP_DUTY_BUY_PCT = 0.003


def leg_charges(premium: float, qty: int, is_buy: bool) -> float:
    turnover = premium * qty
    brokerage = min(turnover * BROKERAGE_PCT / 100.0, BROKERAGE_PER_ORDER)
    stt = 0.0 if is_buy else turnover * STT_SELL_PCT / 100.0
    exchange = turnover * EXCHANGE_TXN_PCT / 100.0
    sebi = turnover * SEBI_PCT / 100.0
    stamp = turnover * STAMP_DUTY_BUY_PCT / 100.0 if is_buy else 0.0
    gst = (brokerage + exchange + sebi) * GST_PCT / 100.0
    return brokerage + stt + exchange + sebi + stamp + gst


def nearest_strike(strikes: pd.Series, target: float) -> float:
    return strikes.iloc[(strikes - target).abs().argsort().iloc[0]]


def run_iron_condor(df: pd.DataFrame, short_offset: float = 200, long_offset: float = 400) -> pd.DataFrame:
    thursdays = sorted(df[df["TradDt"].dt.dayofweek == 3]["TradDt"].unique())
    rows = []

    for entry_date in thursdays:
        day_df = df[df["TradDt"] == entry_date]
        if day_df.empty:
            continue
        cmp_ = day_df["UndrlygPric"].iloc[0]
        lot_size = int(day_df["NewBrdLotQty"].iloc[0])

        future_expiries = sorted(e for e in day_df["XpryDt"].unique() if e > entry_date)
        if not future_expiries:
            continue
        expiry = future_expiries[0]  # nearest weekly expiry

        ce_strikes = day_df[(day_df["XpryDt"] == expiry) & (day_df["OptnTp"] == "CE")]["StrkPric"]
        pe_strikes = day_df[(day_df["XpryDt"] == expiry) & (day_df["OptnTp"] == "PE")]["StrkPric"]
        if ce_strikes.empty or pe_strikes.empty:
            continue

        sell_ce_strike = nearest_strike(ce_strikes, cmp_ + short_offset)
        buy_ce_strike = nearest_strike(ce_strikes, cmp_ + long_offset)
        sell_pe_strike = nearest_strike(pe_strikes, cmp_ - short_offset)
        buy_pe_strike = nearest_strike(pe_strikes, cmp_ - long_offset)

        legs = [
            ("sell_ce", "CE", sell_ce_strike, False),
            ("buy_ce", "CE", buy_ce_strike, True),
            ("sell_pe", "PE", sell_pe_strike, False),
            ("buy_pe", "PE", buy_pe_strike, True),
        ]

        entry_prices = {}
        ok = True
        for name, opt_type, strike, is_buy in legs:
            match = day_df[(day_df["XpryDt"] == expiry) & (day_df["OptnTp"] == opt_type) & (day_df["StrkPric"] == strike)]
            if match.empty:
                ok = False
                break
            entry_prices[name] = match["ClsPric"].iloc[0]
        if not ok:
            continue

        exit_day_df = df[(df["TradDt"] == expiry)]
        if exit_day_df.empty:
            continue
        exit_prices = {}
        for name, opt_type, strike, is_buy in legs:
            match = exit_day_df[(exit_day_df["XpryDt"] == expiry) & (exit_day_df["OptnTp"] == opt_type) & (exit_day_df["StrkPric"] == strike)]
            if match.empty:
                ok = False
                break
            exit_prices[name] = match["ClsPric"].iloc[0]
        if not ok:
            continue

        gross = 0.0
        charges = 0.0
        for name, opt_type, strike, is_buy in legs:
            entry_p, exit_p = entry_prices[name], exit_prices[name]
            sign = 1 if is_buy else -1  # buy: profit if price rises; sell: profit if price falls
            gross += (exit_p - entry_p) * sign * lot_size
            charges += leg_charges(entry_p, lot_size, is_buy) + leg_charges(exit_p, lot_size, is_buy)

        net_credit = entry_prices["sell_ce"] + entry_prices["sell_pe"] - entry_prices["buy_ce"] - entry_prices["buy_pe"]

        rows.append({
            "entry_date": entry_date, "expiry": expiry, "cmp": cmp_, "lot_size": lot_size,
            "sell_ce": sell_ce_strike, "buy_ce": buy_ce_strike,
            "sell_pe": sell_pe_strike, "buy_pe": buy_pe_strike,
            "net_credit_per_share": net_credit,
            "gross_pnl": gross, "charges": charges, "net_pnl": gross - charges,
        })

    return pd.DataFrame(rows)


def main():
    df = pd.read_csv(DATA_PATH, parse_dates=["TradDt", "XpryDt"])
    results = run_iron_condor(df)

    pd.set_option("display.width", 220)
    print(f"Weeks tested: {len(results)}")
    print(results.to_string(index=False))
    if not results.empty:
        print(f"\nTotal net P&L: Rs {results['net_pnl'].sum():,.2f}")
        print(f"Win rate: {(results['net_pnl'] > 0).mean()*100:.1f}%")
        print(f"Avg net P&L per week: Rs {results['net_pnl'].mean():,.2f}")
        print(f"Best week: Rs {results['net_pnl'].max():,.2f}, Worst week: Rs {results['net_pnl'].min():,.2f}")


if __name__ == "__main__":
    main()
