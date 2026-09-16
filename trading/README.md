# ANGELONE Intraday Trading System

A Python intraday trading system for the NSE stock **ANGELONE**, built on the
Zerodha Kite Connect API (`kiteconnect`). Ships with one strategy — an Opening
Range Breakout (ORB) — but is structured so more strategies can be dropped in
via `config/config.yaml` without touching `data.py`, `backtest.py` or
`paper_trader.py`.

## Layout

```
config/config.yaml   # symbol, quantity, strategy params, costs, risk limits
.env                  # Kite API credentials (copy from .env.example, never commit)
config.py             # typed config loader
models.py             # shared Candle / Signal / Trade dataclasses
costs.py              # Zerodha brokerage/STT/exchange charges + slippage model
risk.py               # daily max-loss + manual kill switch
auth.py               # generates today's Kite access token
data.py               # downloads/caches 12 months of 5-min candles
strategies/
  base.py             # StrategyEngine interface (candle in -> signals out)
  orb.py              # Opening Range Breakout implementation
backtest.py           # runs a strategy over cached history, produces reports
paper_trader.py       # live tick -> 5-min candle -> strategy -> simulated fills
```

## Setup

```bash
cd trading
pip install -r requirements.txt
cp .env.example .env      # fill in KITE_API_KEY / KITE_API_SECRET
python auth.py            # daily: generates KITE_ACCESS_TOKEN into .env
```

Edit `config/config.yaml` to change the symbol, quantity, strategy parameters,
brokerage assumptions, or the daily loss limit.

## Strategy: Opening Range Breakout

- Range = high/low of 09:15–09:30 candles.
- Long: 5-min close breaks above the range high, close is above VWAP, and
  volume exceeds the trailing 20-bar average. Short is the mirror image.
- Stop = the tighter (configurable to "wider") of {range midpoint, 0.6% of
  entry}.
- Initial target = 1.5x the initial risk. Once hit, the stop switches to
  trailing the 10-period EMA of closes instead of booking immediately.
- The day is skipped entirely if the opening range is <0.3% or >1.5% of price.
- At most one long and one short entry per day.
- All open positions are force-closed by 15:10.

The same `strategies/orb.py` engine instance processes candles one at a time
in both `backtest.py` and `paper_trader.py`, so backtested behavior and live
(paper) behavior are guaranteed to match.

## Backtest

```bash
python data.py        # populate/update the local 12-month candle cache
python backtest.py
```

Simulates fills with slippage and full Zerodha-style intraday equity charges
(brokerage, STT, exchange transaction charges, SEBI charges, stamp duty, GST)
for a fixed 1000-share quantity (configurable). Prints win rate, average
win/loss, max drawdown, and a daily P&L distribution / monthly equity curve,
and writes `reports/trades.csv`, `reports/daily_pnl.csv`,
`reports/monthly_equity.csv` plus PNG charts.

## Paper trading (live, no real orders)

```bash
python paper_trader.py
```

Connects to Kite Ticker for live ticks during market hours, aggregates them
into 5-minute candles, feeds the same ORB engine, and logs every signal and
simulated fill to `logs/signals_<date>.csv` and `logs/paper_trader_<date>.log`.
**No order-placement API is ever called** — positions are tracked and priced
purely in-process.

## Risk controls

- Hard daily max loss of ₹3,000 (realized + mark-to-market unrealized),
  configurable in `config/config.yaml` under `risk.max_daily_loss`. Once
  breached, `paper_trader.py` force-flattens any open simulated position and
  blocks new entries for the rest of the day; `backtest.py` enforces the same
  rule so simulated results reflect the same discipline.
- Manual kill switch: create a file at `trading/KILL_SWITCH` (path
  configurable) at any time to immediately halt new trading and flatten the
  simulated position.

## Adding another strategy

1. Add a `strategies/<name>.py` implementing `StrategyEngine`
   (`on_new_day`, `on_candle`, `has_open_position`, `force_exit`).
2. Register it in `strategies/__init__.py`'s `_REGISTRY`.
3. Add its parameters under `strategies:` in `config/config.yaml` and point
   `active_strategy` at it.

`data.py`, `backtest.py` and `paper_trader.py` need no changes.
