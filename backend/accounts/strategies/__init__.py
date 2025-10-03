# backend/accounts/strategies/__init__.py
from .common import ensure_ema_cols, cum_from_returns, apply_fee_on_bars
from .ema_stack import ema_stack_long, ema_stack_short, ema_stack_long_short, build_trades
from .kalman import kalman_long, kalman_short, kalman_cross, attach_kalman_cols
from .lorentzian import lorentzian_trades_advta, lorentzian_strategy_advta

__all__ = [
    "ensure_ema_cols","cum_from_returns","apply_fee_on_bars",
    "ema_stack_long","ema_stack_short","ema_stack_long_short","build_trades",
    "kalman_long","kalman_short","kalman_cross","attach_kalman_cols",
    "lorentzian_trades_advta","lorentzian_strategy_advta",
]
