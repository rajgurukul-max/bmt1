"""One-off, manually-directed live intraday range trade on ANGELONE, per explicit
user instruction on 2026-09-17. NOT part of the strategies/ framework — this is a
single day's discretionary plan, executed with real orders on Zerodha.

Plan:
  1. SELL 10 @ 296-297 (short entry, waits for LTP to actually enter the band)
  2. GTT OCO exit for the short: BUY 10 @ 293 (target) or BUY 10 @ 301.5 (stop)
  3. GTT single reversal entry: BUY 10 @ 290.5 if LTP <= 290
  4. GTT OCO exit for the reversal long (placed reactively once #3 fills):
     SELL 10 @ 295.5 (target) or SELL 10 @ 285.5 (stop)

Steps 2 and 4 are only placed once their corresponding entry is confirmed filled,
to avoid an exit-side GTT firing before the position it's meant to protect exists.
"""
import sys
import time
import logging

sys.path.insert(0, "/home/user/bmt1/trading")

from config import load_config
from data import get_kite_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("live_range_trade")

SYMBOL = "ANGELONE"
EXCHANGE = "NSE"
QTY = 10

cfg = load_config()
kite = get_kite_client(cfg)


def wait_for_entry_and_sell(low: float, high: float, max_wait_s: int = 300, poll_s: int = 5):
    logger.info("Waiting for LTP to enter %.2f-%.2f to place SELL entry...", low, high)
    waited = 0
    while waited <= max_wait_s:
        ltp = kite.ltp([f"{EXCHANGE}:{SYMBOL}"])[f"{EXCHANGE}:{SYMBOL}"]["last_price"]
        logger.info("LTP=%.2f", ltp)
        if low <= ltp <= high:
            try:
                order_id = kite.place_order(
                    variety=kite.VARIETY_REGULAR,
                    exchange=EXCHANGE,
                    tradingsymbol=SYMBOL,
                    transaction_type=kite.TRANSACTION_TYPE_SELL,
                    quantity=QTY,
                    product=kite.PRODUCT_MIS,
                    order_type=kite.ORDER_TYPE_MARKET,
                )
            except Exception:
                logger.exception("SELL entry order REJECTED by Kite at LTP=%.2f", ltp)
                raise
            logger.info("SELL entry placed at LTP=%.2f, order_id=%s", ltp, order_id)
            return order_id, ltp
        time.sleep(poll_s)
        waited += poll_s
    logger.warning("Timed out waiting for entry range after %ds.", max_wait_s)
    return None, None


def place_exit_oco(target_price: float, stop_trigger: float, stop_order_price: float, is_short: bool):
    """Exit OCO for an existing position. is_short=True means we BUY to cover; False means SELL to close a long."""
    side = kite.TRANSACTION_TYPE_BUY if is_short else kite.TRANSACTION_TYPE_SELL
    ltp = kite.ltp([f"{EXCHANGE}:{SYMBOL}"])[f"{EXCHANGE}:{SYMBOL}"]["last_price"]

    trigger_values = sorted([target_price, stop_trigger])
    lower, upper = trigger_values
    lower_price = target_price if target_price == lower else stop_order_price
    upper_price = stop_order_price if stop_trigger == upper else target_price

    orders = [
        {"exchange": EXCHANGE, "tradingsymbol": SYMBOL, "transaction_type": side,
         "quantity": QTY, "order_type": "LIMIT", "product": kite.PRODUCT_MIS, "price": lower_price},
        {"exchange": EXCHANGE, "tradingsymbol": SYMBOL, "transaction_type": side,
         "quantity": QTY, "order_type": "LIMIT", "product": kite.PRODUCT_MIS, "price": upper_price},
    ]
    try:
        gtt_id = kite.place_gtt(
            trigger_type=kite.GTT_TYPE_OCO,
            tradingsymbol=SYMBOL,
            exchange=EXCHANGE,
            trigger_values=trigger_values,
            last_price=ltp,
            orders=orders,
        )
    except Exception:
        logger.exception("Exit OCO GTT REJECTED (position may be UNPROTECTED right now)")
        raise
    logger.info("Exit OCO GTT placed: id=%s triggers=%s orders=%s", gtt_id, trigger_values, orders)
    return gtt_id


def place_reversal_entry_gtt(trigger: float, order_price: float):
    ltp = kite.ltp([f"{EXCHANGE}:{SYMBOL}"])[f"{EXCHANGE}:{SYMBOL}"]["last_price"]
    orders = [{
        "exchange": EXCHANGE, "tradingsymbol": SYMBOL, "transaction_type": kite.TRANSACTION_TYPE_BUY,
        "quantity": QTY, "order_type": "LIMIT", "product": kite.PRODUCT_MIS, "price": order_price,
    }]
    try:
        gtt_id = kite.place_gtt(
            trigger_type=kite.GTT_TYPE_SINGLE,
            tradingsymbol=SYMBOL,
            exchange=EXCHANGE,
            trigger_values=[trigger],
            last_price=ltp,
            orders=orders,
        )
    except Exception:
        logger.exception("Reversal entry GTT REJECTED")
        raise
    logger.info("Reversal entry GTT placed: id=%s trigger=%s order_price=%s", gtt_id, trigger, order_price)
    return gtt_id


if __name__ == "__main__":
    import json

    result = {}

    # Step 3: pre-stage the reversal entry now (safe — it's a fresh entry, no sequencing hazard)
    reversal_gtt_id = place_reversal_entry_gtt(trigger=290, order_price=290.5)
    result["reversal_entry_gtt_id"] = reversal_gtt_id

    # Step 1: wait for price back into 296-297, then market sell
    order_id, fill_ltp = wait_for_entry_and_sell(296, 297)
    result["short_entry_order_id"] = order_id
    result["short_entry_ltp"] = fill_ltp

    if order_id:
        time.sleep(2)  # let the market order settle before staging its exit
        # Step 2: exit OCO for the short — BUY to cover at 293 (target) or 301.5 (stop, trigger 301)
        exit_gtt_id = place_exit_oco(target_price=293, stop_trigger=301, stop_order_price=301.5, is_short=True)
        result["short_exit_gtt_id"] = exit_gtt_id

    print(json.dumps(result, indent=2))
