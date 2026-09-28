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


def run_iron_condor(
    df: pd.DataFrame, short_offset: float = 200, long_offset: float = 400,
    stop_loss_credit_multiple: float | None = None, entry_weekday: int | None = 3,
    days_to_expiry: int | None = None, pct_offsets: bool = False,
    sides: tuple[str, ...] = ("CE", "PE"),
    enter_prior_close: bool = False,
    put_short_offset: float | None = None, put_long_offset: float | None = None,
    breach_exit_sides: tuple[str, ...] = (),
    explicit_schedule: list[tuple[pd.Timestamp, pd.Timestamp]] | None = None,
    stop_loss_amount: float | None = None,
) -> pd.DataFrame:
    """stop_loss_amount: fixed rupee stop, in the same units as net_pnl (one lot,
    i.e. qty = lot_size), e.g. 5000 for a Rs 25k stop at 5 lots. Checked at daily
    closes like the credit-multiple stop; if both are set the tighter one wins.
    The exit is at that close, so a gap day can realize well past the limit.

    explicit_schedule: list of (entry_date, expiry) pairs to trade exactly,
    overriding entry_weekday/days_to_expiry/enter_prior_close. Needed when the
    target isn't simply "nearest expiry", e.g. N days before each MONTHLY expiry
    while weekly contracts are still listed alongside it.

    put_short_offset / put_long_offset: put-wing distances from CMP, same units
    as short_offset/long_offset. None (default) mirrors the call side, i.e. a
    symmetric condor. Set wider to push the put side further out of the money.

    breach_exit_sides: e.g. ("PE",) closes that side's whole vertical spread at
    the first interim daily close where spot has crossed its short strike (below
    the short PE / above the short CE); the other side keeps running. Daily
    closes only -- an intraday touch that recovers by the close isn't seen.

    enter_prior_close: if True, each selected signal day (e.g. a Friday) is
    entered at the PREVIOUS trading day's close instead of its own close, while
    still targeting the expiry the signal day would have targeted (nearest
    expiry strictly after the signal day). Bhavcopy has no intraday prices, so
    this is the closest real traded proxy for a signal-day morning entry: the
    prior close sits just before the next open, rather than ~6 hours after it.
    Self-adjusts across expiry regimes -- in a Thursday-expiry week the prior
    day IS expiry day, and the expiring contract is skipped automatically.

    sides: which vertical spreads to run -- ("CE", "PE") for the full 4-leg
    iron condor (default), ("CE",) for a call-credit-spread only (sell_ce/buy_ce),
    or ("PE",) for a put-credit-spread only. Useful for isolating which side of
    a condor was actually carrying the edge (or the risk).

    pct_offsets: if True, short_offset/long_offset are read as PERCENT of that
    day's CMP instead of literal index points (e.g. short_offset=0.82 means
    0.82% OTM). Needed for anything whose price level isn't stable like Nifty's
    -- a single stock's price can drift or jump on a split/bonus within the
    backtest window (verified: RELIANCE roughly halved mid-window on a 1:1
    bonus issue), so a fixed point offset would silently mean a different %
    OTM before and after. Percent offsets stay correct through that.

    stop_loss_credit_multiple: if set, exits the WHOLE position (all 4 legs) at
    the first intervening trading day's close where the mark-to-market loss
    exceeds this multiple of the net credit received at entry -- e.g. 2.0 means
    "stop out once you're down 2x the credit collected". None (default) holds to
    expiry regardless, as in the original spec.

    entry_weekday: 0=Monday .. 4=Friday (default 3=Thursday, the original spec).
    The exit is always the nearest FUTURE expiry found in the data, so
    entry_weekday=0 (Monday) lands on the SAME week's expiry -- a short hold --
    while later weekdays land on the FOLLOWING week's expiry, a longer hold.
    Ignored if days_to_expiry is set.

    days_to_expiry: if set, overrides entry_weekday entirely and instead selects
    every trading day whose nearest future expiry falls EXACTLY this many
    calendar days later -- e.g. 4 reproduces Nifty's winning "Friday entry,
    following Tuesday expiry" gap (Fri -> Tue is 4 calendar days) but does so by
    the actual entry-to-expiry gap rather than a fixed weekday name. This matters
    when the underlying's own expiry weekday isn't stable across the backtest
    window (e.g. Sensex has used Friday, Tuesday, and Thursday expiries within
    the same 2-year span) -- a fixed weekday can silently land on a different
    holding period depending on which regime was in force that week, whereas a
    fixed days-to-expiry filter reproduces the same gap regardless of regime."""
    if days_to_expiry is not None:
        entry_days = []
        for d in sorted(df["TradDt"].unique()):
            day_df = df[df["TradDt"] == d]
            future_expiries = sorted(e for e in day_df["XpryDt"].unique() if e > d)
            if future_expiries and (future_expiries[0] - d).days == days_to_expiry:
                entry_days.append(d)
    else:
        entry_days = sorted(df[df["TradDt"].dt.dayofweek == entry_weekday]["TradDt"].unique())

    all_days = sorted(df["TradDt"].unique())
    if explicit_schedule is not None:
        schedule = [(pd.Timestamp(e), pd.Timestamp(e), pd.Timestamp(x)) for e, x in explicit_schedule]
    elif enter_prior_close:
        day_index = {d: i for i, d in enumerate(all_days)}
        schedule = [(all_days[day_index[d] - 1], d, None) for d in entry_days if day_index[d] > 0]
    else:
        schedule = [(d, d, None) for d in entry_days]
    rows = []

    for entry_date, signal_date, fixed_expiry in schedule:
        day_df = df[df["TradDt"] == entry_date]
        if day_df.empty:
            continue
        cmp_ = day_df["UndrlygPric"].iloc[0]
        lot_size = int(day_df["NewBrdLotQty"].iloc[0])

        if fixed_expiry is not None:
            if fixed_expiry not in set(day_df["XpryDt"].unique()):
                continue
            expiry = fixed_expiry
        else:
            future_expiries = sorted(e for e in day_df["XpryDt"].unique() if e > signal_date)
            if not future_expiries:
                continue
            expiry = future_expiries[0]  # nearest weekly expiry after the signal day

        ce_strikes = day_df[(day_df["XpryDt"] == expiry) & (day_df["OptnTp"] == "CE")]["StrkPric"]
        pe_strikes = day_df[(day_df["XpryDt"] == expiry) & (day_df["OptnTp"] == "PE")]["StrkPric"]
        if ("CE" in sides and ce_strikes.empty) or ("PE" in sides and pe_strikes.empty):
            continue

        def to_pts(offset: float) -> float:
            return cmp_ * offset / 100.0 if pct_offsets else offset

        short_pts, long_pts = to_pts(short_offset), to_pts(long_offset)
        put_short_pts = short_pts if put_short_offset is None else to_pts(put_short_offset)
        put_long_pts = long_pts if put_long_offset is None else to_pts(put_long_offset)

        legs = []
        if "CE" in sides:
            sell_ce_strike = nearest_strike(ce_strikes, cmp_ + short_pts)
            buy_ce_strike = nearest_strike(ce_strikes, cmp_ + long_pts)
            legs += [("sell_ce", "CE", sell_ce_strike, False), ("buy_ce", "CE", buy_ce_strike, True)]
        if "PE" in sides:
            sell_pe_strike = nearest_strike(pe_strikes, cmp_ - put_short_pts)
            buy_pe_strike = nearest_strike(pe_strikes, cmp_ - put_long_pts)
            legs += [("sell_pe", "PE", sell_pe_strike, False), ("buy_pe", "PE", buy_pe_strike, True)]
        strike_of = {name: strike for name, _, strike, _ in legs}

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

        net_credit = sum(entry_prices[name] * (-1 if is_buy else 1) for name, _, _, is_buy in legs)

        exit_prices = {}
        exit_reason = "expiry"
        exit_day = expiry
        open_names = {name for name, _, _, _ in legs}
        breached = []

        if stop_loss_credit_multiple is not None or stop_loss_amount is not None or breach_exit_sides:
            thresholds = []
            if stop_loss_credit_multiple is not None:
                thresholds.append(-abs(stop_loss_credit_multiple) * net_credit * lot_size)
            if stop_loss_amount is not None:
                thresholds.append(-abs(stop_loss_amount))
            stop_threshold = max(thresholds) if thresholds else None
            interim_days = sorted(d for d in df["TradDt"].unique() if entry_date < d < expiry)
            for d in interim_days:
                day_check_df = df[df["TradDt"] == d]
                if day_check_df.empty:
                    continue
                check_prices, complete = {}, True
                for name, opt_type, strike, is_buy in legs:
                    if name not in open_names:
                        continue
                    match = day_check_df[(day_check_df["XpryDt"] == expiry) & (day_check_df["OptnTp"] == opt_type) & (day_check_df["StrkPric"] == strike)]
                    if match.empty:
                        complete = False
                        break
                    check_prices[name] = match["ClsPric"].iloc[0]
                if not complete:
                    continue

                spot = day_check_df["UndrlygPric"].iloc[0]
                for side in breach_exit_sides:
                    short_name = "sell_ce" if side == "CE" else "sell_pe"
                    if short_name not in open_names:
                        continue
                    crossed = spot > strike_of[short_name] if side == "CE" else spot < strike_of[short_name]
                    if crossed:
                        for name, opt_type, _, _ in legs:
                            if opt_type == side and name in open_names:
                                exit_prices[name] = check_prices[name]
                                open_names.discard(name)
                        breached.append(side)
                        exit_day = d
                if not open_names:
                    break

                if stop_threshold is not None:
                    mtm = sum(
                        (exit_prices.get(name, check_prices.get(name)) - entry_prices[name]) * (1 if is_buy else -1) * lot_size
                        for name, _, _, is_buy in legs
                    )
                    if mtm <= stop_threshold:
                        for name in open_names:
                            exit_prices[name] = check_prices[name]
                        open_names.clear()
                        exit_reason = "stop_loss"
                        exit_day = d
                        break

        if breached and exit_reason == "expiry":
            exit_reason = "+".join(breached) + "_breach"

        if open_names:
            exit_day = expiry
            # Held to expiry: cash-settled index options settle at INTRINSIC VALUE
            # against the final settlement price, not at a bhavcopy "close" price.
            # This is generically more correct (not just a workaround), and it also
            # sidesteps a real BSE bhavcopy defect where every SENSEX expiry-day row
            # has ClsPric overwritten with the underlying spot price instead of the
            # option's own settlement value (verified: 100% of SENSEX expiry rows
            # have ClsPric == UndrlygPric == SttlmPric, vs 0% on NIFTY and on any
            # non-expiry day for either index).
            exit_day_df = df[(df["TradDt"] == expiry)]
            if exit_day_df.empty:
                continue
            settlement_price = exit_day_df["UndrlygPric"].iloc[0]
            for name, opt_type, strike, is_buy in legs:
                if name not in open_names:
                    continue
                if opt_type == "CE":
                    exit_prices[name] = max(0.0, settlement_price - strike)
                else:
                    exit_prices[name] = max(0.0, strike - settlement_price)

        gross = 0.0
        charges = 0.0
        for name, opt_type, strike, is_buy in legs:
            entry_p, exit_p = entry_prices[name], exit_prices[name]
            sign = 1 if is_buy else -1  # buy: profit if price rises; sell: profit if price falls
            gross += (exit_p - entry_p) * sign * lot_size
            charges += leg_charges(entry_p, lot_size, is_buy) + leg_charges(exit_p, lot_size, is_buy)

        strikes = {name: strike for name, _, strike, _ in legs}
        rows.append({
            "entry_date": entry_date, "expiry": expiry, "exit_day": exit_day, "exit_reason": exit_reason,
            "cmp": cmp_, "lot_size": lot_size,
            **strikes,
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
