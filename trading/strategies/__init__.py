from strategies.base import StrategyEngine
from strategies.orb import OpeningRangeBreakoutEngine

_REGISTRY = {
    "orb": OpeningRangeBreakoutEngine,
}


def create_strategy_engine(name: str, params: dict, qty: int, market_cfg) -> StrategyEngine:
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {list(_REGISTRY)}"
        ) from exc
    return cls(params=params, qty=qty, market_cfg=market_cfg)
