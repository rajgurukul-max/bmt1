from strategies.base import StrategyEngine
from strategies.orb import OpeningRangeBreakoutEngine
from strategies.vwap_reversion import VwapReversionEngine
from strategies.rsi_ema_reversal import RsiEmaReversalEngine
from strategies.bollinger_reversion import BollingerReversionEngine
from strategies.ema_crossover import EmaCrossoverEngine
from strategies.prev_day_breakout import PrevDayBreakoutEngine

_REGISTRY = {
    "orb": OpeningRangeBreakoutEngine,
    "orb_trend": OpeningRangeBreakoutEngine,
    "vwap_reversion": VwapReversionEngine,
    "rsi_ema_reversal": RsiEmaReversalEngine,
    "bollinger_reversion": BollingerReversionEngine,
    "ema_crossover": EmaCrossoverEngine,
    "prev_day_breakout": PrevDayBreakoutEngine,
}


def create_strategy_engine(name: str, params: dict, qty: int, market_cfg) -> StrategyEngine:
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {list(_REGISTRY)}"
        ) from exc
    return cls(params=params, qty=qty, market_cfg=market_cfg)
