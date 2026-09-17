from strategies.base import StrategyEngine
from strategies.orb import OpeningRangeBreakoutEngine
from strategies.vwap_reversion import VwapReversionEngine

_REGISTRY = {
    "orb": OpeningRangeBreakoutEngine,
    "vwap_reversion": VwapReversionEngine,
}


def create_strategy_engine(name: str, params: dict, qty: int, market_cfg) -> StrategyEngine:
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {list(_REGISTRY)}"
        ) from exc
    return cls(params=params, qty=qty, market_cfg=market_cfg)
