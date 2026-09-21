from strategies.base import StrategyEngine
from strategies.orb import OpeningRangeBreakoutEngine
from strategies.vwap_reversion import VwapReversionEngine
from strategies.rsi_ema_reversal import RsiEmaReversalEngine

_REGISTRY = {
    "orb": OpeningRangeBreakoutEngine,
    "orb_trend": OpeningRangeBreakoutEngine,
    "vwap_reversion": VwapReversionEngine,
    "rsi_ema_reversal": RsiEmaReversalEngine,
}


def create_strategy_engine(name: str, params: dict, qty: int, market_cfg) -> StrategyEngine:
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {list(_REGISTRY)}"
        ) from exc
    return cls(params=params, qty=qty, market_cfg=market_cfg)
