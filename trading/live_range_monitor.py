"""Long-running watcher for the 2026-09-17 ANGELONE live range trade.

Runs until square-off time, each cycle:
  1. If the short hasn't been entered yet: watch for LTP in [296, 297] -> market
     SELL 10, then immediately place its exit OCO (293 target / 301 stop).
  2. Watch the pre-placed reversal entry GTT (trigger 290 -> BUY 10). Once it has
     fired, place its exit OCO (295.5 target / 286 stop) reactively.

Logs every action to logs/live_range_trade_2026-09-17.log. Real orders/GTTs only
placed on the documented conditions above.
"""
import sys
import time
import logging
from datetime import datetime, time as dtime
import pytz

sys.path.insert(0, "/home/user/bmt1/trading")

from config import load_config
from data import get_kite_client

cfg = load_config()
tz = pytz.timezone(cfg.market.timezone)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(cfg.logging.log_dir / "live_range_trade_2026-09-17.log"),
    ],
)
logger = logging.getLogger("live_range_monitor")

kite = get_kite_client(cfg)

SYMBOL = "ANGELONE"
EXCHANGE = "NSE"
QTY = 10
SQUARE_OFF_T = dtime(15, 10)
REVERSAL_GTT_ID = 336458568

STATE_FILE = cfg.data.cache_dir.parent / "live_range_trade_state.json"


def load_state() -> dict:
    import json
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"short_entered": False, "short_exit_placed": False, "reversal_exit_placed": False}


def save_state(state: dict) -> None:
    import json
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_ltp() -> float:
    return kite.ltp([f"{EXCHANGE}:{SYMBOL}"])[f"{EXCHANGE}:{SYMBOL}"]["last_price"]


def place_short_entry() -> str:
    order_id = kite.place_order(
        variety=kite.VARIETY_REGULAR, exchange=EXCHANGE, tradingsymbol=SYMBOL,
        transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=QTY,
        product=kite.PRODUCT_MIS, order_type=kite.ORDER_TYPE_MARKET,
    )
    logger.info("SHORT ENTRY placed, order_id=%s", order_id)
    return order_id


def place_short_exit_oco() -> dict:
    ltp = get_ltp()
    orders = [
        {"exchange": EXCHANGE, "tradingsymbol": SYMBOL, "transaction_type": kite.TRANSACTION_TYPE_BUY,
         "quantity": QTY, "order_type": "LIMIT", "product": kite.PRODUCT_MIS, "price": 293},
        {"exchange": EXCHANGE, "tradingsymbol": SYMBOL, "transaction_type": kite.TRANSACTION_TYPE_BUY,
         "quantity": QTY, "order_type": "LIMIT", "product": kite.PRODUCT_MIS, "price": 301.5},
    ]
    gtt = kite.place_gtt(
        trigger_type=kite.GTT_TYPE_OCO, tradingsymbol=SYMBOL, exchange=EXCHANGE,
        trigger_values=[293, 301], last_price=ltp, orders=orders,
    )
    logger.info("SHORT EXIT OCO placed: %s", gtt)
    return gtt


def place_reversal_exit_oco() -> dict:
    ltp = get_ltp()
    orders = [
        {"exchange": EXCHANGE, "tradingsymbol": SYMBOL, "transaction_type": kite.TRANSACTION_TYPE_SELL,
         "quantity": QTY, "order_type": "LIMIT", "product": kite.PRODUCT_MIS, "price": 285.5},
        {"exchange": EXCHANGE, "tradingsymbol": SYMBOL, "transaction_type": kite.TRANSACTION_TYPE_SELL,
         "quantity": QTY, "order_type": "LIMIT", "product": kite.PRODUCT_MIS, "price": 295.5},
    ]
    gtt = kite.place_gtt(
        trigger_type=kite.GTT_TYPE_OCO, tradingsymbol=SYMBOL, exchange=EXCHANGE,
        trigger_values=[286, 295.5], last_price=ltp, orders=orders,
    )
    logger.info("REVERSAL EXIT OCO placed: %s", gtt)
    return gtt


def reversal_gtt_fired() -> bool:
    gtt = kite.get_gtt(REVERSAL_GTT_ID)
    status = gtt.get("status")
    if status != kite.GTT_STATUS_ACTIVE:
        logger.info("Reversal GTT status=%s (details: %s)", status, gtt)
    return status == kite.GTT_STATUS_TRIGGERED


def main():
    state = load_state()
    logger.info("Monitor starting. State: %s", state)

    while True:
        now_t = datetime.now(tz).time()
        if now_t >= SQUARE_OFF_T:
            logger.info("Reached square-off time, stopping monitor.")
            break

        try:
            if not state["short_entered"]:
                ltp = get_ltp()
                if 296 <= ltp <= 297:
                    place_short_entry()
                    state["short_entered"] = True
                    save_state(state)
                    time.sleep(2)
                    place_short_exit_oco()
                    state["short_exit_placed"] = True
                    save_state(state)

            if not state["reversal_exit_placed"] and reversal_gtt_fired():
                place_reversal_exit_oco()
                state["reversal_exit_placed"] = True
                save_state(state)
        except Exception:
            logger.exception("Error in monitor loop iteration; will retry next cycle.")

        if state["short_entered"] and state["reversal_exit_placed"]:
            logger.info("Both legs fully handled. Monitor exiting.")
            break

        time.sleep(5)


if __name__ == "__main__":
    main()
